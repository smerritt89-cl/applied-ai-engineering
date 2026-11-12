"""Tests for lab 03. All offline: no API key, no GPU, and no torch required.

Run:  pytest studio-5/03-lora-finetune -q

One optional test compares your parameter count with what PEFT actually builds on a tiny
randomly initialized Qwen2 model. It runs only if torch, transformers, and peft are
installed (see the README), and is skipped otherwise.
"""
from __future__ import annotations

import json
import math
import pathlib
import re

import pytest

import make_lora_data as data_gen
import starter as lab

HERE = pathlib.Path(__file__).parent

# Qwen/Qwen2.5-0.5B-Instruct config.json (the keys that matter), checked on the review date.
QWEN25_05B = {
    "hidden_size": 896,
    "intermediate_size": 4864,
    "num_attention_heads": 14,
    "num_key_value_heads": 2,
    "num_hidden_layers": 24,
}

RECORD = {
    "ticket": "Order ORD-12345 hasn't arrived. We need this fixed today.",
    "label": {"category": "shipping", "priority": "high", "product": None, "order_id": "ORD-12345"},
}


# ---------------------------------------------------------------- 1. formatting


def test_label_to_json_is_canonical():
    label = {"order_id": None, "product": "API", "priority": "high", "category": "bug", "extra": 1}
    assert lab.label_to_json(label) == '{"category": "bug", "priority": "high", "product": "API", "order_id": null}'


def test_prompt_completion_shape():
    ex = lab.to_prompt_completion(RECORD)
    assert [m["role"] for m in ex["prompt"]] == ["system", "user"]
    assert ex["prompt"][0]["content"] == lab.SYSTEM_PROMPT
    assert ex["prompt"][1]["content"] == RECORD["ticket"]
    assert [m["role"] for m in ex["completion"]] == ["assistant"]
    assert json.loads(ex["completion"][0]["content"]) == RECORD["label"]


def test_messages_for_mlx_end_with_the_answer():
    msgs = lab.to_messages(RECORD)["messages"]
    assert [m["role"] for m in msgs] == ["system", "user", "assistant"]
    assert json.loads(msgs[-1]["content"]) == RECORD["label"]


def test_render_chatml_matches_qwen_structure():
    msgs = [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}]
    assert lab.render_chatml(msgs) == "<|im_start|>system\nS<|im_end|>\n<|im_start|>user\nU<|im_end|>\n"
    assert lab.render_chatml(msgs, add_generation_prompt=True).endswith("<|im_start|>assistant\n")


def test_render_chatml_inserts_default_system():
    out = lab.render_chatml([{"role": "user", "content": "hi"}])
    assert out.startswith(f"<|im_start|>system\n{lab.QWEN_DEFAULT_SYSTEM}<|im_end|>\n")
    assert out.endswith("<|im_start|>user\nhi<|im_end|>\n")


def test_split_prompt_completion_trains_only_the_answer():
    prompt_text, completion_text = lab.split_prompt_completion(lab.to_prompt_completion(RECORD))
    assert prompt_text.endswith("<|im_start|>assistant\n")
    assert RECORD["ticket"] in prompt_text, "the ticket belongs to the prompt (masked)"
    assert RECORD["ticket"] not in completion_text, "the ticket must not get loss"
    assert completion_text == lab.label_to_json(RECORD["label"]) + "<|im_end|>\n", (
        "the trained text is the answer plus the end-of-turn marker: that marker is how the model learns to stop"
    )


def test_split_prompt_completion_rejects_non_prefix(monkeypatch):
    # A template that renders the prompt differently on its own than inside the full
    # conversation would make position-based masking wrong. Simulate one.
    def bad_render(messages, add_generation_prompt=False):
        text = "".join(m["content"] for m in messages)
        return ("GEN:" + text) if add_generation_prompt else text

    monkeypatch.setattr(lab, "render_chatml", bad_render)
    with pytest.raises(ValueError):
        lab.split_prompt_completion(lab.to_prompt_completion(RECORD))


# ---------------------------------------------------------------- 2. parameter counts


def test_linear_shapes_with_grouped_query_attention():
    shapes = lab.linear_shapes(QWEN25_05B)
    assert shapes["q_proj"] == (896, 896)
    assert shapes["k_proj"] == (896, 128), "k and v use num_key_value_heads * head_dim = 2 * 64"
    assert shapes["v_proj"] == (896, 128)
    assert shapes["o_proj"] == (896, 896)
    assert shapes["gate_proj"] == (896, 4864)
    assert shapes["up_proj"] == (896, 4864)
    assert shapes["down_proj"] == (4864, 896)


def test_linear_shapes_respects_explicit_head_dim():
    cfg = dict(QWEN25_05B, head_dim=128)
    assert lab.linear_shapes(cfg)["q_proj"] == (896, 14 * 128)
    cfg_null = dict(QWEN25_05B, head_dim=None)
    assert lab.linear_shapes(cfg_null)["q_proj"] == (896, 896)


def test_lora_params_all_linear_qwen25_05b():
    # 24 blocks * 16 * (2*(896+896) + 2*(896+128) + 3*(896+4864)) = 8,798,208
    assert lab.lora_trainable_params(QWEN25_05B, r=16) == 8_798_208
    total = 494_032_768  # parameter count reported on the model page
    share = 8_798_208 / total
    assert 0.017 < share < 0.018, "about 1.8 percent of the base model"


def test_lora_params_attention_only_and_linearity_in_r():
    qv8 = lab.lora_trainable_params(QWEN25_05B, r=8, targets=("q_proj", "v_proj"))
    assert qv8 == 24 * 8 * ((896 + 896) + (896 + 128)) == 540_672
    assert lab.lora_trainable_params(QWEN25_05B, r=16, targets=("q_proj", "v_proj")) == 2 * qv8


def test_lora_params_rejects_unknown_target():
    with pytest.raises(KeyError):
        lab.lora_trainable_params(QWEN25_05B, r=8, targets=("q_proj", "lm_head"))


def test_lora_count_matches_peft_on_a_tiny_model():
    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    peft = pytest.importorskip("peft")
    cfg = {"hidden_size": 64, "intermediate_size": 160, "num_attention_heads": 4,
           "num_key_value_heads": 2, "num_hidden_layers": 2}
    torch.manual_seed(0)
    model = transformers.Qwen2ForCausalLM(transformers.Qwen2Config(vocab_size=128, **cfg))
    peft_model = peft.get_peft_model(model, peft.LoraConfig(r=4, lora_alpha=8, target_modules="all-linear"))
    trainable, _ = peft_model.get_nb_trainable_parameters()
    assert trainable == lab.lora_trainable_params(cfg, r=4)


# ---------------------------------------------------------------- 3. loss curves

HF_LOG = [
    {"loss": 2.91, "grad_norm": 3.1, "learning_rate": 1e-4, "epoch": 0.1, "step": 5},
    {"loss": 1.20, "grad_norm": 2.0, "learning_rate": 2e-4, "epoch": 0.2, "step": 10},
    {"eval_loss": 1.05, "eval_runtime": 1.2, "epoch": 0.2, "step": 10},
    {"loss": 0.40, "epoch": 0.3, "step": 15},
    {"loss": 0.21, "epoch": 0.4, "step": 20},
    {"eval_loss": 0.38, "epoch": 0.4, "step": 20},
    {"loss": 0.05, "epoch": 0.5, "step": 25},
    {"eval_loss": 0.45, "epoch": 0.6, "step": 30},
    {"loss": 0.02, "epoch": 0.7, "step": 35},
    {"eval_loss": 0.52, "epoch": 0.8, "step": 40},
    {"train_runtime": 99.0, "train_loss": 0.6, "epoch": 1.0, "step": 40},
]


def test_parse_log_history_splits_and_skips_summary():
    train, evals = lab.parse_log_history(HF_LOG)
    assert train == [(5, 2.91), (10, 1.20), (15, 0.40), (20, 0.21), (25, 0.05), (35, 0.02)]
    assert evals == [(10, 1.05), (20, 0.38), (30, 0.45), (40, 0.52)]


def test_parse_mlx_jsonl():
    lines = [
        '{"iteration": 1, "val_loss": 3.2, "val_time": 0.5}',
        '{"iteration": 10, "train_loss": 2.1, "learning_rate": 0.0002}',
        "",
        '{"iteration": 20, "train_loss": 1.4}',
        '{"iteration": 20, "val_loss": 1.6}',
    ]
    train, evals = lab.parse_mlx_jsonl(lines)
    assert train == [(10, 2.1), (20, 1.4)]
    assert evals == [(1, 3.2), (20, 1.6)]


def test_diagnose_flags_overfitting():
    train, evals = lab.parse_log_history(HF_LOG)
    d = lab.diagnose(train, evals)
    assert d["best_eval_step"] == 20 and d["best_eval_loss"] == 0.38
    assert d["final_eval_loss"] == 0.52
    assert d["overfitting"] is True, "eval loss rose for two evals after its minimum while train loss kept falling"
    assert d["nonfinite"] is False


def test_diagnose_respects_patience_and_min_delta():
    evals = [(10, 1.0), (20, 0.5), (30, 0.52)]
    assert lab.diagnose([], evals, patience=2)["overfitting"] is False, "one rise is not enough with patience 2"
    assert lab.diagnose([], evals, patience=1)["overfitting"] is True
    assert lab.diagnose([], evals, patience=1, min_delta=0.05)["overfitting"] is False, "a rise within min_delta is noise"


def test_diagnose_handles_nan_and_empty():
    d = lab.diagnose([(5, 1.0), (10, float("nan"))], [(10, float("nan")), (20, 0.9)])
    assert d["nonfinite"] is True
    assert d["best_eval_step"] == 20, "ignore non-finite evals when picking the best"
    empty = lab.diagnose([(5, 1.0)], [])
    assert empty["best_eval_step"] is None and empty["overfitting"] is False


def test_diagnose_ties_pick_earliest():
    d = lab.diagnose([], [(10, 0.5), (20, 0.5), (30, 0.6)], patience=1)
    assert d["best_eval_step"] == 10


# ---------------------------------------------------------------- 4. scoring

GOLD = {"category": "bug", "priority": "high", "product": "API", "order_id": None}


def test_score_exact_match():
    s = lab.score_prediction('  {"category": "bug", "priority": "high", "product": "API", "order_id": null}\n', GOLD)
    assert s == {"valid_json": True, "fields_correct": 4, "exact": True}


def test_score_partial_and_extra_keys():
    s = lab.score_prediction('{"category": "bug", "priority": "low", "product": "API", "order_id": null}', GOLD)
    assert s == {"valid_json": True, "fields_correct": 3, "exact": False}
    extra = lab.score_prediction(
        '{"category": "bug", "priority": "high", "product": "API", "order_id": null, "note": "x"}', GOLD
    )
    assert extra["fields_correct"] == 4 and extra["exact"] is False, "extra keys break the output contract"


@pytest.mark.parametrize(
    "text",
    [
        '```json\n{"category": "bug", "priority": "high", "product": "API", "order_id": null}\n```',
        'Sure! {"category": "bug"}',
        '["bug", "high"]',
        "",
    ],
)
def test_score_rejects_non_object_output(text):
    s = lab.score_prediction(text, GOLD)
    assert s["valid_json"] is False and s["fields_correct"] == 0 and s["exact"] is False


def test_summarize_scores():
    scores = [
        {"valid_json": True, "fields_correct": 4, "exact": True},
        {"valid_json": True, "fields_correct": 2, "exact": False},
        {"valid_json": False, "fields_correct": 0, "exact": False},
        {"valid_json": True, "fields_correct": 4, "exact": True},
    ]
    s = lab.summarize_scores(scores)
    assert s["n"] == 4
    assert math.isclose(s["valid_json_rate"], 0.75)
    assert math.isclose(s["field_accuracy"], 10 / 16)
    assert math.isclose(s["exact_match"], 0.5)
    assert lab.summarize_scores([])["n"] == 0


# ---------------------------------------------------------------- data and notebook


def _template_regex(template: str) -> re.Pattern:
    pattern = re.escape(template)
    for slot in ("product", "order", "urgency"):
        pattern = pattern.replace(re.escape("{" + slot + "}"), ".+?")
    return re.compile("^" + pattern + "$")


def test_committed_data_matches_generator():
    built = data_gen.build()
    for split, rows in built.items():
        lines = (HERE / "data" / f"{split}.jsonl").read_text().splitlines()
        assert [json.loads(x) for x in lines] == rows, f"data/{split}.jsonl is stale: rerun make_lora_data.py"


def test_test_split_uses_held_out_templates():
    built = data_gen.build()
    train_templates = [_template_regex(t) for ts in data_gen.TEMPLATES.values() for t in ts[:-2]]
    for row in built["test"]:
        assert not any(rx.match(row["ticket"]) for rx in train_templates), row["ticket"]


def test_notebook_is_valid_and_unexecuted():
    nb = json.loads((HERE / "finetune.ipynb").read_text())
    assert nb["nbformat"] == 4
    code = [c for c in nb["cells"] if c["cell_type"] == "code"]
    assert len(code) >= 8
    for cell in code:
        assert cell.get("outputs") == [] and cell.get("execution_count") is None, "commit the notebook without outputs"
    source = "".join("".join(c["source"]) for c in nb["cells"])
    assert "Qwen/Qwen2.5-0.5B-Instruct" in source
    assert "SFTTrainer" in source and "LoraConfig" in source
