#!/usr/bin/env python3
"""
Pre-generate lesson narration with Kokoro, an open-weight text-to-speech model.

How it fits together
--------------------
1. `npm run build` renders every lesson. Each <Listen> section is written to the
   HTML with `data-hash` (a hash of its narration text) and `data-narration`
   (the text itself).
2. This script scans the built HTML, and for every hash that has no audio yet
   it synthesizes speech sentence by sentence, joins the clips, encodes a small
   mono MP3 with ffmpeg, and writes a WebVTT caption file whose cues line up
   exactly with the sentences.
3. `public/audio/manifest.json` records each hash's duration. The next build
   sees the files and switches that section's player from the browser voice to
   the generated audio.

Edit a paragraph and its hash changes, so only that section is regenerated.

Usage (from the repo root):
    npm run audio                      # build, then generate what's missing
    python scripts/tts/generate.py --prune   # also delete audio no lesson uses

Model: Kokoro-82M (Apache 2.0, https://huggingface.co/hexgrad/Kokoro-82M) run
through the kokoro-onnx package (MIT, https://github.com/thewh1teagle/kokoro-onnx).
The ONNX model files (~340 MB) download on first run into scripts/tts/models/
(gitignored).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODELS = Path(__file__).resolve().parent / "models"
AUDIO = ROOT / "public" / "audio"
MANIFEST = AUDIO / "manifest.json"

MODEL_FILES = {
    "kokoro-v1.0.onnx": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
    "voices-v1.0.bin": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
}
SAMPLE_RATE = 24_000
PAUSE_SECONDS = 0.28  # silence between sentences
BITRATE = "48k"  # mono speech: about 360 KB per minute


# ---------------------------------------------------------------------------
# 1. Find narration sections in the built site
# ---------------------------------------------------------------------------
class ListenFinder(HTMLParser):
    """Collects (hash, text) from elements carrying data-listen."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: dict[str, str] = {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "data-listen" in a and a.get("data-hash") and a.get("data-narration"):
            self.found[a["data-hash"]] = a["data-narration"]


def collect_sections(dist: Path) -> dict[str, str]:
    sections: dict[str, str] = {}
    for html in dist.rglob("*.html"):
        finder = ListenFinder()
        finder.feed(html.read_text(encoding="utf-8"))
        sections.update(finder.found)
    return sections


# ---------------------------------------------------------------------------
# 2. Text preparation
# ---------------------------------------------------------------------------
SENTENCE_RE = re.compile(r"[^.!?]+[.!?]+[\"')\]]*|\S[^.!?]*$")


def split_sentences(text: str) -> list[str]:
    """Split into sentences; very long ones are split again at commas or semicolons."""
    out: list[str] = []
    for s in (m.group(0).strip() for m in SENTENCE_RE.finditer(text)):
        if not s:
            continue
        if len(s) <= 300:
            out.append(s)
            continue
        part = ""
        for piece in re.split(r"(?<=[,;:])\s+", s):
            if len(part) + len(piece) > 280 and part:
                out.append(part.strip())
                part = ""
            part += piece + " "
        if part.strip():
            out.append(part.strip())
    return out


# Pronunciation fixes for terms the model reads badly. Extend as you hear them.
SPEAK_AS = {
    r"\bLLMs\b": "L L Ms",
    r"\bLLM\b": "L L M",
    r"\bAPIs\b": "A P Is",
    r"\bAPI\b": "A P I",
    r"\bJSON\b": "jason",
    r"\bRAG\b": "rag",
    r"\bMCP\b": "M C P",
    r"\bSDK\b": "S D K",
    r"\bCSV\b": "C S V",
    r"\bLoRA\b": "lora",
    r"\bGPT\b": "G P T",
    r"\bPRs?\b": "pull request",
    r"\be\.g\.": "for example",
    r"\bi\.e\.": "that is",
    r"\bvs\.?": "versus",
    r"_": " ",
}


def speakable(sentence: str) -> str:
    s = sentence
    for pattern, repl in SPEAK_AS.items():
        s = re.sub(pattern, repl, s)
    return s


# ---------------------------------------------------------------------------
# 3. Synthesis
# ---------------------------------------------------------------------------
def ensure_models() -> None:
    MODELS.mkdir(parents=True, exist_ok=True)
    for name, url in MODEL_FILES.items():
        dest = MODELS / name
        if dest.exists() and dest.stat().st_size > 1_000_000:
            continue
        print(f"Downloading {name} (first run only)…", flush=True)
        tmp = dest.with_suffix(".part")
        urllib.request.urlretrieve(url, tmp)
        tmp.rename(dest)


def vtt_time(t: float) -> str:
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"


def synthesize(kokoro, text: str, voice: str, speed: float):
    import numpy as np

    pause = np.zeros(int(SAMPLE_RATE * PAUSE_SECONDS), dtype=np.float32)
    clips, cues, t = [], [], 0.0
    for sentence in split_sentences(text):
        samples, sr = kokoro.create(speakable(sentence), voice=voice, speed=speed, lang="en-us")
        assert sr == SAMPLE_RATE, f"unexpected sample rate {sr}"
        dur = len(samples) / sr
        cues.append((t, t + dur, sentence))
        clips += [samples.astype(np.float32), pause]
        t += dur + PAUSE_SECONDS
    audio = np.concatenate(clips) if clips else np.zeros(1, dtype=np.float32)
    return audio, cues, t


def write_outputs(h: str, audio, cues, duration: float) -> None:
    import soundfile as sf

    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / f"{h}.wav"
        sf.write(wav, audio, SAMPLE_RATE)
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-y", "-i", str(wav), "-ac", "1", "-b:a", BITRATE, str(AUDIO / f"{h}.mp3")],
            check=True,
        )
    lines = ["WEBVTT", ""]
    for i, (a, b, s) in enumerate(cues, 1):
        lines += [str(i), f"{vtt_time(a)} --> {vtt_time(b)}", s, ""]
    (AUDIO / f"{h}.vtt").write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dist", default=str(ROOT / "dist"), help="built site to scan (default: dist/)")
    ap.add_argument("--voice", default="af_heart", help="Kokoro voice id (default: af_heart)")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--prune", action="store_true", help="delete audio files no lesson references")
    ap.add_argument("--force", action="store_true", help="regenerate everything")
    ap.add_argument("--limit", type=int, default=0, help="generate at most N sections (for testing)")
    args = ap.parse_args()

    dist = Path(args.dist)
    if not dist.exists():
        print(f"No build found at {dist}. Run `npm run build` first.", file=sys.stderr)
        return 1

    AUDIO.mkdir(parents=True, exist_ok=True)
    manifest: dict = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    sections = collect_sections(dist)
    todo = {
        h: t
        for h, t in sections.items()
        if args.force or h not in manifest or not (AUDIO / f"{h}.mp3").exists()
    }
    if args.limit:
        todo = dict(list(todo.items())[: args.limit])
    print(f"{len(sections)} narration sections found, {len(todo)} need audio.")

    if todo:
        ensure_models()
        from kokoro_onnx import Kokoro

        kokoro = Kokoro(str(MODELS / "kokoro-v1.0.onnx"), str(MODELS / "voices-v1.0.bin"))
        for i, (h, text) in enumerate(todo.items(), 1):
            started = time.time()
            audio, cues, duration = synthesize(kokoro, text, args.voice, args.speed)
            write_outputs(h, audio, cues, duration)
            manifest[h] = {"duration": round(duration, 2), "voice": args.voice}
            MANIFEST.write_text(json.dumps(manifest, indent=1, sort_keys=True))  # save as we go
            print(f"[{i}/{len(todo)}] {h}: {duration:5.1f}s audio in {time.time() - started:4.1f}s  {text[:60]}…", flush=True)

    if args.prune:
        removed = 0
        for f in AUDIO.glob("*.*"):
            if f.name != "manifest.json" and f.stem not in sections:
                f.unlink()
                removed += 1
        manifest = {h: v for h, v in manifest.items() if h in sections}
        MANIFEST.write_text(json.dumps(manifest, indent=1, sort_keys=True))
        print(f"Pruned {removed} unused files.")

    total = sum(v["duration"] for h, v in manifest.items() if h in sections)
    print(f"Done. {total / 60:.1f} minutes of narration across {len(sections)} sections.")
    print("Run `npm run build` again so pages pick up the new audio.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
