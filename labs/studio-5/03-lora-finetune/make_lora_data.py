"""Generate the synthetic support-ticket triage dataset for lab 03.

Every record is {"ticket": str, "label": {"category", "priority", "product", "order_id"}}.
The data is synthetic and template-based, written for this course. Run it to rebuild data/:

    python make_lora_data.py

The split is by TEMPLATE, not by row: each category has templates reserved for the
validation and test sets that never appear in training. A random row split would put
near-copies of the same sentence in train and test and make the fine-tuned model look
better than it is.
"""
from __future__ import annotations

import json
import pathlib
import random

SEED = 20261111
DATA_DIR = pathlib.Path(__file__).parent / "data"

PRODUCTS = ["mobile app", "web dashboard", "API", "invoice portal"]

# Phrases that set priority. The label follows the phrase, so the rule is learnable.
URGENCY = {
    "high": ["This is blocking our whole team.", "We need this fixed today.", "Production is down because of this."],
    "medium": ["Can you take a look?", "Please advise.", "Let me know what you find."],
    "low": ["No rush on this one.", "Whenever you get a chance.", "Not urgent, just flagging it."],
}

# {product}, {order}, and {urgency} are filled in. Templates without {order} have order_id null.
# The last two templates in each list are held out: index -2 for validation, -1 for test.
TEMPLATES = {
    "billing": [
        "I was charged twice for order {order} in the {product}. {urgency}",
        "The invoice for {order} shows the wrong amount. {urgency}",
        "Why did my card get billed again this month? I only use the {product}. {urgency}",
        "Our finance team sees a refund missing for {order}. {urgency}",
        "The {product} says my payment failed, but the bank shows it went through for {order}. {urgency}",
        "We were billed for seats we cancelled last quarter. {urgency}",
    ],
    "bug": [
        "The {product} crashes when I open the reports tab. {urgency}",
        "Export to CSV in the {product} produces an empty file. {urgency}",
        "Since the last update the {product} logs me out every few minutes. {urgency}",
        "Order {order} shows as shipped in the {product} but the status page says pending. {urgency}",
        "Search in the {product} returns results from the wrong account. {urgency}",
        "Every request to the {product} returns a 500 error since this morning. {urgency}",
    ],
    "account": [
        "I can't reset my password for the {product}. {urgency}",
        "Please add a new admin to our workspace in the {product}. {urgency}",
        "Two-factor codes for the {product} never arrive. {urgency}",
        "We need to transfer ownership of our account to a new manager. {urgency}",
        "My colleague was removed from the {product} by mistake. {urgency}",
        "How do I change the email address on our account? {urgency}",
    ],
    "shipping": [
        "Order {order} hasn't arrived and tracking hasn't updated in a week. {urgency}",
        "The box for {order} arrived damaged. {urgency}",
        "Can I change the delivery address for {order}? {urgency}",
        "We received the wrong item in {order}. {urgency}",
        "Order {order} was marked delivered but nobody here received it. {urgency}",
        "Part of order {order} is missing from the package. {urgency}",
    ],
    "feature_request": [
        "It would help if the {product} could schedule reports by email. {urgency}",
        "Could you add dark mode to the {product}? {urgency}",
        "We'd love bulk editing in the {product}. {urgency}",
        "Please support single sign-on for the {product}. {urgency}",
        "Any plans to let the {product} export to PDF? {urgency}",
        "It would be great to tag tickets by team in the {product}. {urgency}",
    ],
}

FIELDS = ("category", "priority", "product", "order_id")


def _order_id(rng: random.Random) -> str:
    return f"ORD-{rng.randint(10000, 99999)}"


def make_record(category: str, template: str, rng: random.Random) -> dict:
    priority = rng.choice(list(URGENCY))
    product = rng.choice(PRODUCTS) if "{product}" in template else None
    order = _order_id(rng) if "{order}" in template else None
    ticket = template.format(product=product or "", order=order or "", urgency=rng.choice(URGENCY[priority]))
    return {
        "ticket": ticket,
        "label": {"category": category, "priority": priority, "product": product, "order_id": order},
    }


def build(n_train: int = 300, n_valid: int = 50, n_test: int = 50, seed: int = SEED) -> dict[str, list[dict]]:
    """Return {"train": [...], "valid": [...], "test": [...]} with a template-level split."""
    rng = random.Random(seed)
    pools = {
        "train": [(c, t) for c, ts in TEMPLATES.items() for t in ts[:-2]],
        "valid": [(c, ts[-2]) for c, ts in TEMPLATES.items()],
        "test": [(c, ts[-1]) for c, ts in TEMPLATES.items()],
    }
    sizes = {"train": n_train, "valid": n_valid, "test": n_test}
    out: dict[str, list[dict]] = {}
    for split, pool in pools.items():
        rows = []
        for i in range(sizes[split]):
            category, template = pool[i % len(pool)]
            rows.append(make_record(category, template, rng))
        rng.shuffle(rows)
        out[split] = rows
    return out


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    for split, rows in build().items():
        path = DATA_DIR / f"{split}.jsonl"
        with path.open("w") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")
        print(f"wrote {len(rows):>3} rows to {path}")


if __name__ == "__main__":
    main()
