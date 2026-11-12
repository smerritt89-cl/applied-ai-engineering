"""Outline of a tiny character-level GPT training script (needs PyTorch).

This is scaffolding, not a finished model. The data pipeline, evaluation, logging, and
sampling are written for you; the model classes are yours to write, following
"Let's build GPT" (lesson e1-w4-l7). Compare your finished code with Karpathy's
ng-video-lecture gpt.py and nanoGPT model.py (both MIT) only after you've written your own.

Usage (from labs/electives/e1-tiny-gpt, after finishing starter.py):

    pip install torch
    python train_outline.py --corpus data/my_book.txt --check-data      # no torch needed
    python train_outline.py --corpus data/my_book.txt --max-iters 2000 --run-name base

Each run appends one row per evaluation to runs/<run-name>.csv (step, train_loss, val_loss,
seconds) and writes runs/<run-name>-samples.txt. Plot the CSVs for your project report.
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import random
import time

from starter import CharTokenizer, get_batch, strip_gutenberg, train_val_split, uniform_loss

HERE = pathlib.Path(__file__).parent


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--corpus", required=True, help="path to a UTF-8 text file you have the right to use")
    p.add_argument("--gutenberg", action="store_true", help="strip Project Gutenberg header and footer")
    p.add_argument("--check-data", action="store_true", help="print data statistics and exit (no torch)")
    p.add_argument("--block-size", type=int, default=64, help="context length in characters")
    p.add_argument("--n-embd", type=int, default=128)
    p.add_argument("--n-head", type=int, default=4)
    p.add_argument("--n-layer", type=int, default=4)
    p.add_argument("--dropout", type=float, default=0.0)
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--max-iters", type=int, default=2000)
    p.add_argument("--eval-interval", type=int, default=200)
    p.add_argument("--eval-iters", type=int, default=50, help="batches averaged per split per evaluation")
    p.add_argument("--seed", type=int, default=1337)
    p.add_argument("--run-name", default="run")
    return p.parse_args()


def load_data(args):
    text = pathlib.Path(args.corpus).read_text(encoding="utf-8")
    if args.gutenberg:
        text = strip_gutenberg(text)
    tok = CharTokenizer.from_text(text)
    ids = tok.encode(text)
    train, val = train_val_split(ids, 0.1)
    return text, tok, train, val


# ---------------------------------------------------------------- the model (yours to write)

def build_model(vocab_size: int, args):
    """Return your GPT as a torch.nn.Module with forward(idx, targets=None) -> (logits, loss).

    Suggested pieces, in the order the lecture builds them:
      Head            one causal self-attention head (key, query, value projections, a lower-
                      triangular mask, scores scaled by head_size ** -0.5, softmax, weighted sum)
      MultiHead       n_head heads in parallel, concatenated, then a linear projection
      FeedForward     Linear(n_embd, 4 * n_embd), a nonlinearity, Linear(4 * n_embd, n_embd)
      Block           x = x + attention(ln1(x)); x = x + ffwd(ln2(x))   (pre-norm residual)
      GPT             token and position embeddings, n_layer blocks, final LayerNorm, linear head
    Use torch.nn.functional.cross_entropy for the loss (reshape logits to (B*T, V)).
    Add a generate(idx, max_new_tokens, temperature=1.0) method that crops the context to the
    last block_size tokens and samples one token at a time.
    """
    raise NotImplementedError("write your GPT here, following lesson e1-w4-l7")


# ---------------------------------------------------------------- training, evaluation, logging

def main() -> None:
    args = parse_args()
    text, tok, train, val = load_data(args)
    print(f"characters: {len(text):,}  vocab: {tok.vocab_size}  train: {len(train):,}  val: {len(val):,}")
    print(f"uniform baseline loss: {uniform_loss(tok.vocab_size):.4f}  (your step-0 loss should be close)")
    if args.check_data:
        rng = random.Random(args.seed)
        xs, ys = get_batch(train, args.block_size, 2, rng)
        print("example input :", repr(tok.decode(xs[0])))
        print("example target:", repr(tok.decode(ys[0])))
        return

    import torch  # imported here so --check-data works without torch

    torch.manual_seed(args.seed)
    rng = random.Random(args.seed)
    device = "cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu")
    model = build_model(tok.vocab_size, args).to(device)
    n_params = sum(p.numel() for p in model.parameters())
    print(f"device: {device}  parameters: {n_params:,}")
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr)

    def batch(split):
        xs, ys = get_batch(train if split == "train" else val, args.block_size, args.batch_size, rng)
        return torch.tensor(xs, device=device), torch.tensor(ys, device=device)

    @torch.no_grad()
    def estimate_loss():
        model.eval()  # turns dropout off
        out = {}
        for split in ("train", "val"):
            losses = [model(*batch(split))[1].item() for _ in range(args.eval_iters)]
            out[split] = sum(losses) / len(losses)
        model.train()
        return out

    runs = HERE / "runs"
    runs.mkdir(exist_ok=True)
    log_path = runs / f"{args.run_name}.csv"
    (runs / f"{args.run_name}-config.json").write_text(json.dumps(vars(args) | {"params": n_params}, indent=2))
    start = time.time()
    with log_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["step", "train_loss", "val_loss", "seconds"])
        for step in range(args.max_iters + 1):
            if step % args.eval_interval == 0 or step == args.max_iters:
                losses = estimate_loss()
                writer.writerow([step, f"{losses['train']:.4f}", f"{losses['val']:.4f}", f"{time.time() - start:.1f}"])
                f.flush()
                print(f"step {step:5d}  train {losses['train']:.4f}  val {losses['val']:.4f}")
            if step == args.max_iters:
                break
            xb, yb = batch("train")
            _, loss = model(xb, yb)
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()

    model.eval()
    context = torch.zeros((1, 1), dtype=torch.long, device=device)
    sample = tok.decode(model.generate(context, max_new_tokens=500)[0].tolist())
    (runs / f"{args.run_name}-samples.txt").write_text(sample, encoding="utf-8")
    print(sample)


if __name__ == "__main__":
    main()
