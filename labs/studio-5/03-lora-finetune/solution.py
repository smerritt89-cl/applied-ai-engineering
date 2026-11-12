"""Lab 03 reference solution: the pure-Python parts of a LoRA fine-tuning run.

Nothing here imports torch, so the offline tests run anywhere. The notebook
(finetune.ipynb) and the MLX script (mlx_finetune.py) import these helpers.
"""
from __future__ import annotations

import json
import math

SYSTEM_PROMPT = (
    "You triage customer support tickets. Reply with only a JSON object with the keys "
    '"category" (billing, bug, account, shipping, or feature_request), '
    '"priority" (low, medium, or high), "product" (mobile app, web dashboard, API, invoice portal, or null), '
    'and "order_id" (the order number exactly as written, or null).'
)

FIELDS = ("category", "priority", "product", "order_id")

# Qwen2.5's chat template inserts this system message when a conversation has none.
QWEN_DEFAULT_SYSTEM = "You are Qwen, created by Alibaba Cloud. You are a helpful assistant."

# Module names used by Llama, Qwen2, Mistral, and similar decoder blocks.
ALL_LINEAR = ("q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj")


# ------------------------------------------------------------ 1. formatting


def label_to_json(label: dict) -> str:
    """Serialize a label as compact JSON with keys in FIELDS order."""
    return json.dumps({k: label[k] for k in FIELDS})


def to_prompt_completion(record: dict, system_prompt: str = SYSTEM_PROMPT) -> dict:
    """Convert a raw record to TRL's conversational prompt-completion format."""
    return {
        "prompt": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": record["ticket"]},
        ],
        "completion": [{"role": "assistant", "content": label_to_json(record["label"])}],
    }


def to_messages(record: dict, system_prompt: str = SYSTEM_PROMPT) -> dict:
    """Convert a raw record to the chat format MLX-LM expects (one "messages" list)."""
    pc = to_prompt_completion(record, system_prompt)
    return {"messages": pc["prompt"] + pc["completion"]}


def render_chatml(messages: list[dict], add_generation_prompt: bool = False) -> str:
    """Render messages the way Qwen2.5's chat template does (no tools, no tool calls)."""
    parts = []
    if not messages or messages[0]["role"] != "system":
        parts.append(f"<|im_start|>system\n{QWEN_DEFAULT_SYSTEM}<|im_end|>\n")
    for m in messages:
        parts.append(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n")
    if add_generation_prompt:
        parts.append("<|im_start|>assistant\n")
    return "".join(parts)


def split_prompt_completion(example: dict) -> tuple[str, str]:
    """Return (prompt_text, completion_text) for a prompt-completion example.

    prompt_text is the prompt rendered with the generation prompt; completion_text is
    what remains of the full conversation. Raise ValueError if the prompt rendering is
    not a prefix of the full rendering (then masking by position would be wrong).
    """
    prompt_text = render_chatml(example["prompt"], add_generation_prompt=True)
    full_text = render_chatml(example["prompt"] + example["completion"])
    if not full_text.startswith(prompt_text):
        raise ValueError("prompt rendering is not a prefix of the full conversation")
    return prompt_text, full_text[len(prompt_text):]


# ------------------------------------------------------------ 2. parameter counts


def linear_shapes(config: dict) -> dict[str, tuple[int, int]]:
    """(in_features, out_features) of each linear layer in one decoder block."""
    h = config["hidden_size"]
    n_heads = config["num_attention_heads"]
    n_kv = config.get("num_key_value_heads", n_heads)
    head_dim = config.get("head_dim") or h // n_heads
    ff = config["intermediate_size"]
    return {
        "q_proj": (h, n_heads * head_dim),
        "k_proj": (h, n_kv * head_dim),
        "v_proj": (h, n_kv * head_dim),
        "o_proj": (n_heads * head_dim, h),
        "gate_proj": (h, ff),
        "up_proj": (h, ff),
        "down_proj": (ff, h),
    }


def lora_trainable_params(config: dict, r: int, targets=ALL_LINEAR) -> int:
    """Trainable LoRA parameters: r * (in + out) per targeted layer, times the block count."""
    shapes = linear_shapes(config)
    unknown = set(targets) - set(shapes)
    if unknown:
        raise KeyError(f"unknown target modules: {sorted(unknown)}")
    per_block = sum(r * (shapes[t][0] + shapes[t][1]) for t in targets)
    return per_block * config["num_hidden_layers"]


# ------------------------------------------------------------ 3. loss curves


def parse_log_history(log_history: list[dict]) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """Split a Hugging Face Trainer log_history into (train, eval) lists of (step, loss)."""
    train, evals = [], []
    for entry in log_history:
        if "loss" in entry and "step" in entry:
            train.append((int(entry["step"]), float(entry["loss"])))
        if "eval_loss" in entry and "step" in entry:
            evals.append((int(entry["step"]), float(entry["eval_loss"])))
    return train, evals


def parse_mlx_jsonl(lines: list[str]) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """Parse the JSONL log written by mlx_finetune.py into (train, eval) lists of (step, loss)."""
    train, evals = [], []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        if "train_loss" in rec:
            train.append((int(rec["iteration"]), float(rec["train_loss"])))
        if "val_loss" in rec:
            evals.append((int(rec["iteration"]), float(rec["val_loss"])))
    return train, evals


def diagnose(train: list[tuple[int, float]], evals: list[tuple[int, float]], patience: int = 2,
             min_delta: float = 0.0) -> dict:
    """Summarize a run. Overfitting means the last `patience` evals all sit above the best eval by more than min_delta."""
    all_losses = [loss for _, loss in train] + [loss for _, loss in evals]
    report = {
        "nonfinite": any(not math.isfinite(x) for x in all_losses),
        "best_eval_step": None,
        "best_eval_loss": None,
        "final_eval_loss": None,
        "overfitting": False,
    }
    finite_evals = [(s, x) for s, x in evals if math.isfinite(x)]
    if not finite_evals:
        return report
    best_step, best_loss = min(finite_evals, key=lambda p: (p[1], p[0]))
    report["best_eval_step"] = best_step
    report["best_eval_loss"] = best_loss
    report["final_eval_loss"] = finite_evals[-1][1]
    after = [x for s, x in finite_evals if s > best_step]
    if len(after) >= patience and all(x > best_loss + min_delta for x in after[-patience:]):
        report["overfitting"] = True
    return report


# ------------------------------------------------------------ 4. scoring outputs


def score_prediction(text: str, gold: dict) -> dict:
    """Score one model output against the gold label. Only surrounding whitespace is forgiven."""
    try:
        pred = json.loads(text.strip())
    except (json.JSONDecodeError, TypeError):
        return {"valid_json": False, "fields_correct": 0, "exact": False}
    if not isinstance(pred, dict):
        return {"valid_json": False, "fields_correct": 0, "exact": False}
    correct = sum(1 for k in FIELDS if k in pred and pred[k] == gold[k])
    exact = correct == len(FIELDS) and set(pred) == set(FIELDS)
    return {"valid_json": True, "fields_correct": correct, "exact": exact}


def summarize_scores(scores: list[dict]) -> dict:
    """Aggregate score_prediction results into rates."""
    n = len(scores)
    if n == 0:
        return {"n": 0, "valid_json_rate": 0.0, "field_accuracy": 0.0, "exact_match": 0.0}
    return {
        "n": n,
        "valid_json_rate": sum(s["valid_json"] for s in scores) / n,
        "field_accuracy": sum(s["fields_correct"] for s in scores) / (n * len(FIELDS)),
        "exact_match": sum(s["exact"] for s in scores) / n,
    }
