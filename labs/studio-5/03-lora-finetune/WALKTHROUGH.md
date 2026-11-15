# Walkthrough: Lab 03, LoRA fine-tuning, measured

## What this code does

This lab fine-tunes a small open model (Qwen2.5-0.5B-Instruct) with LoRA so it triages support tickets into a fixed
JSON format. The training itself happens in `finetune.ipynb` (Colab, NVIDIA GPU) or `mlx_finetune.py` (Apple
Silicon). `solution.py`, the file this walkthrough covers, holds the pure-Python helpers those two scripts import:
nothing in it needs torch or a GPU, which is why every test runs on any laptop.

The helpers cover the four judgments a fine-tuning run depends on. **Formatting**: turning records into the chat
format the trainers expect, and checking that only the answer gets loss. **Parameter counts**: how big the adapter
is, computed from the model's config. **Loss curves**: reading the trainer's logs and diagnosing overfitting.
**Scoring**: judging outputs with a strict scorer against a held-out test set, because a falling training loss
says nothing about whether the model is right.

The theme is that the loss curve is not the result. The README's authoring run makes the point: the base model
produced valid JSON for every ticket and got 2 percent exactly right; the tuned adapter reached 52 percent. Only the
scorer tells you that.

## How to read this lab

Open `work.py` in VS Code beside this page. It starts as a copy of `solution.py`, so the line numbers below match
it until you edit it. Read a section here, then the same lines there.

Run the tests from VS Code's **Testing** panel (the flask icon): expand `studio-5/03-lora-finetune` and press run.
All tests are offline; one (`test_lora_count_matches_peft_on_a_tiny_model`) is skipped unless torch, transformers,
and peft are installed. From a terminal: `pytest studio-5/03-lora-finetune -q` from the `labs` folder. The notebook
and MLX script use these same functions, so once `work.py` is right, the training run's numbers are too.

## Constants (lines 11 to 24)

```python
SYSTEM_PROMPT = (
    "You triage customer support tickets. Reply with only a JSON object with the keys "
    ...
)
FIELDS = ("category", "priority", "product", "order_id")
QWEN_DEFAULT_SYSTEM = "You are Qwen, created by Alibaba Cloud. You are a helpful assistant."
ALL_LINEAR = ("q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj")
```

The system prompt is written as several string pieces inside parentheses. Python joins **adjacent string
literals** automatically, which is a tidy way to write a long string without one enormous line. It lists every
allowed value, so the prompt and the scorer agree on the contract.

`FIELDS` is a **tuple** that fixes the order of the label's keys; every function below uses it. `QWEN_DEFAULT_SYSTEM`
is the system message Qwen2.5's chat template inserts when a conversation has none, which matters for rendering
(below). `ALL_LINEAR` names the seven linear layers in a Llama-style decoder block, the usual LoRA targets.

## Formatting: `label_to_json`, `to_prompt_completion`, `to_messages` (lines 30 to 49)

```python
def label_to_json(label: dict) -> str:
    return json.dumps({k: label[k] for k in FIELDS})

def to_prompt_completion(record: dict, system_prompt: str = SYSTEM_PROMPT) -> dict:
    return {
        "prompt": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": record["ticket"]},
        ],
        "completion": [{"role": "assistant", "content": label_to_json(record["label"])}],
    }
```

`label_to_json` uses a **dictionary comprehension** to rebuild the label with keys in `FIELDS` order and nothing
else (an extra key in the source record is dropped). Training targets must be **canonical**: if the same label
were sometimes written with keys in a different order, the model would learn that the order is random, and an exact
scorer would punish it.

`to_prompt_completion` produces TRL's **conversational prompt-completion** format: the prompt (system and user
turns) and the completion (the assistant turn) are kept apart, which is how the trainer knows which tokens to score.
`to_messages` (lines 46 to 49) joins the two lists with `+` into the single `messages` list MLX-LM expects. Building
one from the other guarantees the two training paths see identical text.

## Rendering and the masking check: `render_chatml`, `split_prompt_completion` (lines 52 to 75)

```python
def render_chatml(messages: list[dict], add_generation_prompt: bool = False) -> str:
    parts = []
    if not messages or messages[0]["role"] != "system":
        parts.append(f"<|im_start|>system\n{QWEN_DEFAULT_SYSTEM}<|im_end|>\n")
    for m in messages:
        parts.append(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n")
    if add_generation_prompt:
        parts.append("<|im_start|>assistant\n")
    return "".join(parts)
```

A **chat template** turns a list of messages into the single string the model actually reads. Qwen uses the ChatML
style: each turn is wrapped in `<|im_start|>role` and `<|im_end|>` markers. `add_generation_prompt=True` appends
the opening of an assistant turn, which is what you send at inference to say "your turn". The **f-strings** fill in
the role and content; `"".join(parts)` assembles the pieces.

This function re-implements the template in plain Python so the tests can check rendering without downloading a
tokenizer. In the notebook, the real tokenizer's template does the work. If the two ever disagreed, the offline
checks would be checking the wrong thing; the notebook's "template check" cell exists to compare them.

```python
    prompt_text = render_chatml(example["prompt"], add_generation_prompt=True)
    full_text = render_chatml(example["prompt"] + example["completion"])
    if not full_text.startswith(prompt_text):
        raise ValueError("prompt rendering is not a prefix of the full conversation")
    return prompt_text, full_text[len(prompt_text):]
```

`split_prompt_completion` (lines 64 to 75) answers the masking question from lesson 7: which part of the text gets
loss? Trainers mask by **position**: everything up to the length of the rendered prompt is ignored. That is only
correct if the prompt, rendered on its own, is exactly the beginning of the full conversation. The function checks
that with `str.startswith` and raises `ValueError` if not, because some templates render a prompt differently on its
own (for example, adding or dropping a default system message), and then position-based masking would silently score
the wrong tokens.

`full_text[len(prompt_text):]` is a **slice** from the end of the prompt to the end: the completion text. The test
checks that it is the JSON answer **plus** `<|im_end|>\n`. That end-of-turn marker is trained on purpose: it is how
the model learns to stop. Masking it away is a common mistake, and the symptom is a model that keeps generating
after the answer.

## Parameter counts: `linear_shapes` and `lora_trainable_params` (lines 81 to 106)

```python
    h = config["hidden_size"]
    n_heads = config["num_attention_heads"]
    n_kv = config.get("num_key_value_heads", n_heads)
    head_dim = config.get("head_dim") or h // n_heads
    ...
        "k_proj": (h, n_kv * head_dim),
```

`linear_shapes` reads a model's `config.json` values and returns `(in_features, out_features)` for each linear layer
in one block. Two lines handle real-world config variation:

- `config.get("num_key_value_heads", n_heads)`: older models without **grouped-query attention** have as many KV
  heads as attention heads, so that is the default.
- `config.get("head_dim") or h // n_heads`: some configs state `head_dim` explicitly, some omit it, and some set it
  to `null`. `or` falls back to hidden size divided by heads (`//` is floor division) in both of the last two
  cases. A plain `.get("head_dim", h // n_heads)` would return `None` for a config with `"head_dim": null`, and the
  test with `head_dim=None` catches that.

For Qwen2.5-0.5B, 896 hidden, 14 heads, and 2 KV heads give a head size of 64, so `k_proj` and `v_proj` are only
896 by 128.

```python
    unknown = set(targets) - set(shapes)
    if unknown:
        raise KeyError(f"unknown target modules: {sorted(unknown)}")
    per_block = sum(r * (shapes[t][0] + shapes[t][1]) for t in targets)
    return per_block * config["num_hidden_layers"]
```

`lora_trainable_params` (lines 99 to 106) uses LoRA's count: matrices A (`r` by in) and B (out by `r`) add
`r * (in + out)` parameters per adapted layer. `set(targets) - set(shapes)` is **set difference**: any requested
target that is not a known layer. Raising on it matters because a typo in `target_modules` (or a name like
`lm_head` that isn't in a block) would otherwise count as zero, and you'd train a smaller adapter than you think.

Worked value: at `r=16` on all seven layers, 24 blocks give **8,798,208** trainable parameters, about 1.8 percent of
the model's 494 million. The optional test builds a tiny random Qwen2 model with PEFT and checks this formula
against what PEFT actually creates, which is the right way to trust a hand-derived formula.

## Loss curves: `parse_log_history` and `parse_mlx_jsonl` (lines 112 to 135)

```python
    for entry in log_history:
        if "loss" in entry and "step" in entry:
            train.append((int(entry["step"]), float(entry["loss"])))
        if "eval_loss" in entry and "step" in entry:
            evals.append((int(entry["step"]), float(entry["eval_loss"])))
```

A Hugging Face `Trainer` keeps `log_history`, a list of dictionaries: training-loss entries, evaluation entries,
and a final summary. The function sorts them into two lists of `(step, loss)` **tuples**. Checking for the exact key
`"loss"` is what skips the summary entry, whose key is `"train_loss"`; treating it as one more training point would
add a misleading average to the end of the curve. `int(...)` and `float(...)` normalize the types for plotting and
comparison.

`parse_mlx_jsonl` does the same for the JSONL log that `mlx_finetune.py` writes, where entries use `iteration`,
`train_loss`, and `val_loss`, and blank lines are skipped. Two parsers that return the same shape mean `diagnose`
doesn't care which framework ran.

## `diagnose` (lines 138 to 159)

```python
    finite_evals = [(s, x) for s, x in evals if math.isfinite(x)]
    if not finite_evals:
        return report
    best_step, best_loss = min(finite_evals, key=lambda p: (p[1], p[0]))
    ...
    after = [x for s, x in finite_evals if s > best_step]
    if len(after) >= patience and all(x > best_loss + min_delta for x in after[-patience:]):
        report["overfitting"] = True
```

`diagnose` turns two curves into a few facts: did any loss go non-finite (NaN or infinity, which means training
broke), where was the best evaluation loss, what was the last one, and does the run look like it is overfitting.

- `math.isfinite` filters NaN and infinity before choosing the best, so one broken eval can't be picked as the
  "best" (NaN compares strangely with everything).
- `min(..., key=lambda p: (p[1], p[0]))` picks the lowest loss, and on a tie the earliest step: the **key** is a
  **lambda** returning a tuple, and tuples compare element by element.
- **Overfitting** here means the last `patience` evaluations after the best one are all worse than the best by more
  than `min_delta`. `after[-patience:]` is a **slice** of the last `patience` items. `patience` stops one noisy
  uptick from raising the alarm, and `min_delta` ignores rises too small to matter.

Worked value from the test log: evals of 1.05, 0.38, 0.45, 0.52 at steps 10 to 40. The best is 0.38 at step 20,
and the two evals after it both sit higher, so with `patience=2` the run is flagged, while training loss keeps
falling to 0.02. That divergence is the classic picture of memorizing easy synthetic templates.

A reviewer should notice what `diagnose` does not do: it doesn't tell you the model is good. A run can show no
overfitting and still score poorly. Only the scorer below answers that.

## Scoring: `score_prediction` and `summarize_scores` (lines 165 to 188)

```python
    try:
        pred = json.loads(text.strip())
    except (json.JSONDecodeError, TypeError):
        return {"valid_json": False, "fields_correct": 0, "exact": False}
    if not isinstance(pred, dict):
        return {"valid_json": False, "fields_correct": 0, "exact": False}
    correct = sum(1 for k in FIELDS if k in pred and pred[k] == gold[k])
    exact = correct == len(FIELDS) and set(pred) == set(FIELDS)
```

The scorer is deliberately **strict**: only surrounding whitespace is forgiven. A reply wrapped in a code fence, a
sentence before the JSON, or a JSON list all count as invalid. That is the right standard for a fine-tuned model
whose whole job is to produce this format; a forgiving parser (like lab 01's `extract_json`) would hide the format
failures the fine-tune is supposed to fix.

- **try/except** catches both `JSONDecodeError` (text that isn't JSON) and `TypeError` (a `None` output from a failed
  generation), listed together as a **tuple of exception types**.
- `correct` counts matching fields with a **generator expression**. `k in pred` comes first, so a missing key is
  wrong rather than a `KeyError`.
- `exact` also requires `set(pred) == set(FIELDS)`: extra keys break the output contract even if the four fields
  are right, because a strict downstream system would reject them.

`summarize_scores` (lines 178 to 188) turns per-output scores into rates. Booleans sum as 1 and 0. Field accuracy
divides by `n * len(FIELDS)`, the number of field decisions, and the empty case returns zeros instead of dividing by
zero.

What the scorer can't see: whether an `order_id` was copied from the ticket or invented (the README's `"chango.500"`
example). It only compares with gold, so an invented id on a ticket whose gold id is `null` is just "wrong", with no
hint that the model is making things up. CHANGE.md adds that check.

## What the tests check

- **Formatting** (`test_label_to_json_is_canonical` through `test_split_prompt_completion_rejects_non_prefix`):
  canonical key order, the prompt-completion and messages shapes, ChatML structure including the default system
  message, that only the answer plus `<|im_end|>` is trained, and that a non-prefix template is refused (simulated
  with `monkeypatch`, a pytest tool that temporarily replaces a function).
- **Parameter counts** (`test_linear_shapes_*`, `test_lora_params_*`): grouped-query shapes, explicit and null
  `head_dim`, the Qwen2.5-0.5B total, linearity in `r`, rejecting unknown targets, and (optionally) agreement with
  PEFT on a tiny model.
- **Loss curves** (`test_parse_*`, `test_diagnose_*`): parsing both log formats, skipping the summary entry,
  flagging overfitting, patience and `min_delta`, NaN handling, and tie-breaking.
- **Scoring** (`test_score_*`, `test_summarize_scores`): exact, partial, extra keys, every kind of non-object output,
  and the aggregate rates.
- **Data and notebook**: the committed data matches the generator, the test split uses held-out templates (so it
  measures generalization), and the notebook is committed without outputs.

What they don't cover: the training run itself, whether the real tokenizer's template matches `render_chatml` for
every case (the notebook checks one), and anything about output quality on real tickets. The test split is
synthetic; a production decision needs real, labeled examples.

## Review questions

1. Why does `split_prompt_completion` raise instead of just returning the two strings?

   <details><summary>Answer</summary>

   Trainers mask the prompt by position: the first `len(prompt)` tokens get no loss. If the prompt rendered alone is
   not a prefix of the full conversation, the boundary is in the wrong place, and the model trains on part of the
   prompt or misses part of the answer. Nothing would crash and the loss would still fall, so the function makes the
   problem loud.

   </details>

2. An AI assistant writes `head_dim = config.get("head_dim", h // n_heads)`. Which config breaks it?

   <details><summary>Answer</summary>

   A config with `"head_dim": null`. The key exists, so `.get` returns `None` instead of the default, and the next
   multiplication raises `TypeError`. The `or` form falls back in both the missing and the null case.
   `test_linear_shapes_respects_explicit_head_dim` covers it.

   </details>

3. Training loss falls to 0.02 while eval loss bottoms out at 0.38 and rises to 0.52. What do you do next, and what
   should decide between the options?

   <details><summary>Answer</summary>

   The run is memorizing the training templates. Try fewer steps (or the checkpoint near the best eval), a lower
   learning rate, or more varied data, and compare the runs by their **test scores** from the strict scorer, not by
   their losses. The README makes this point: format improves first, and the loss can't tell you whether categories
   and order ids are right.

   </details>

4. Someone changes `score_prediction` to strip a Markdown code fence before parsing, "to be fair to the base model".
   What does that hide?

   <details><summary>Answer</summary>

   Format failures. The fine-tune's first job is to produce the exact format; a scorer that forgives fences makes the
   base model look better and the improvement from tuning look smaller. If you want both views, report a strict
   score and a lenient one separately and say which is which.

   </details>
