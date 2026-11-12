"""Lab 03, Apple Silicon path: the same LoRA run with MLX-LM instead of PyTorch.

Install (Apple Silicon Mac only), inside labs/.venv or a fresh venv:
    pip install "mlx-lm[train]==0.32.2"

Run from the repo's labs/ folder:
    python studio-5/03-lora-finetune/mlx_finetune.py            # QLoRA on a 4-bit model
    python studio-5/03-lora-finetune/mlx_finetune.py --bf16     # LoRA on the bf16 model

What it does:
    1. Writes data in MLX-LM's chat format to mlx_data/{train,valid,test}.jsonl.
    2. Scores the base model on the test split (greedy decoding, same scorer as the notebook).
    3. Trains a LoRA adapter, logging every train and validation loss to mlx_runs/log.jsonl.
    4. Scores the fine-tuned model on the same test split and prints the loss diagnosis.

Why the Python API and not only the CLI: the CLI prints losses to the terminal but
`mlx_lm.lora`'s run() replaces any callback you pass, so this script calls the same
building blocks (load, load_dataset, train_model) with a callback that writes JSONL.
Those are internal functions, so the version is pinned. The CLI equivalent is printed at
the end; it should reach a similar result.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from types import SimpleNamespace

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))

try:
    import starter as lab
    lab.label_to_json({"category": "", "priority": "", "product": None, "order_id": None})
except NotImplementedError:  # starter not done yet: fall back to the reference
    import solution as lab

MODELS = {
    "4bit": "mlx-community/Qwen2.5-0.5B-Instruct-4bit",  # quantized base: MLX-LM trains QLoRA automatically
    "bf16": "mlx-community/Qwen2.5-0.5B-Instruct-bf16",
}
DATA_DIR = HERE / "mlx_data"
RUN_DIR = HERE / "mlx_runs"


def write_mlx_data() -> dict[str, list[dict]]:
    DATA_DIR.mkdir(exist_ok=True)
    raw = {}
    for split in ("train", "valid", "test"):
        rows = [json.loads(x) for x in (HERE / "data" / f"{split}.jsonl").read_text().splitlines() if x.strip()]
        raw[split] = rows
        with (DATA_DIR / f"{split}.jsonl").open("w") as f:
            for r in rows:
                f.write(json.dumps(lab.to_messages(r)) + "\n")
    return raw


def score(model, tokenizer, rows) -> dict:
    from mlx_lm import generate

    scores = []
    for r in rows:
        messages = lab.to_messages(r)["messages"][:-1]  # drop the gold answer
        prompt = tokenizer.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
        text = generate(model, tokenizer, prompt=prompt, max_tokens=80)  # default sampler is greedy
        scores.append(lab.score_prediction(text, r["label"]))
    return lab.summarize_scores(scores)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--bf16", action="store_true", help="train LoRA on the bf16 model instead of QLoRA on 4-bit")
    p.add_argument("--iters", type=int, default=150)
    p.add_argument("--learning-rate", type=float, default=2e-4)
    p.add_argument("--rank", type=int, default=16)
    p.add_argument("--scale", type=float, default=2.0, help="MLX uses a direct scale, here alpha/r = 32/16")
    opts = p.parse_args()

    from mlx_lm import load
    from mlx_lm.lora import CONFIG_DEFAULTS, train_model
    from mlx_lm.tuner.callbacks import TrainingCallback
    from mlx_lm.tuner.datasets import load_dataset

    model_id = MODELS["bf16" if opts.bf16 else "4bit"]
    raw = write_mlx_data()
    RUN_DIR.mkdir(exist_ok=True)
    log_path = RUN_DIR / "log.jsonl"
    log_path.write_text("")

    class JsonlLogger(TrainingCallback):
        def _write(self, info: dict) -> None:
            clean = {k: (v.item() if hasattr(v, "item") else v) for k, v in info.items()}
            with log_path.open("a") as f:
                f.write(json.dumps(clean) + "\n")

        def on_train_loss_report(self, train_info: dict) -> None:
            self._write(train_info)

        def on_val_loss_report(self, val_info: dict) -> None:
            self._write(val_info)

    args = SimpleNamespace(**{
        **CONFIG_DEFAULTS,
        "model": model_id,
        "train": True,
        "data": str(DATA_DIR),
        "mask_prompt": True,            # loss on the assistant answer only
        "num_layers": -1,               # adapt every block (Qwen2.5-0.5B has 24); the default is the last 16
        "batch_size": 8,
        "iters": opts.iters,
        "learning_rate": opts.learning_rate,
        "steps_per_report": 10,
        "steps_per_eval": 25,
        "adapter_path": str(RUN_DIR / "adapters"),
        "lora_parameters": {"rank": opts.rank, "dropout": 0.05, "scale": opts.scale},
        "seed": 42,
    })

    model, tokenizer = load(model_id)
    print("base model:", score(model, tokenizer, raw["test"]))

    train_set, valid_set, _ = load_dataset(args, tokenizer)
    train_model(args, model, train_set, valid_set, JsonlLogger())

    model.eval()
    print("tuned model:", score(model, tokenizer, raw["test"]))
    train_pts, eval_pts = lab.parse_mlx_jsonl(log_path.read_text().splitlines())
    print("diagnosis:", lab.diagnose(train_pts, eval_pts, patience=2, min_delta=0.01))
    print(f"loss log: {log_path}")
    print(
        "\nCLI equivalent (prints losses instead of writing JSONL):\n"
        f"  mlx_lm.lora --model {model_id} --train --data {DATA_DIR} --mask-prompt "
        f"--num-layers -1 --batch-size 8 --iters {opts.iters} --learning-rate {opts.learning_rate} "
        f"--adapter-path {RUN_DIR / 'adapters'}\n"
        "  (rank, dropout, and scale go in a YAML file passed with -c; see LORA.md)\n"
        f"  mlx_lm.generate --model {model_id} --adapter-path {RUN_DIR / 'adapters'} --prompt \"...\"\n"
        f"  mlx_lm.fuse --model {model_id} --adapter-path {RUN_DIR / 'adapters'}"
    )


if __name__ == "__main__":
    main()
