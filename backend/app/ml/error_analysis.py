"""Error analysis for HFCE evaluation."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def analyze_errors(
    y_true: list[Any],
    y_pred: list[Any],
    *,
    contexts: list[dict[str, Any]] | None = None,
    top_features: list[list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    contexts = contexts or [{} for _ in y_true]
    top_features = top_features or [[] for _ in y_true]
    errors = []
    for i, (t, p) in enumerate(zip(y_true, y_pred)):
        if str(t) != str(p):
            errors.append(
                {
                    "index": i,
                    "true_label": str(t),
                    "predicted_label": str(p),
                    "context": contexts[i],
                    "top_features": top_features[i],
                }
            )
    # confusion pairs
    pairs = Counter((str(t), str(p)) for t, p in zip(y_true, y_pred) if str(t) != str(p))
    # per-class false positives/negatives
    fp = defaultdict(int)
    fn = defaultdict(int)
    for t, p in zip(y_true, y_pred):
        if str(t) != str(p):
            fp[str(p)] += 1
            fn[str(t)] += 1
    return {
        "n_errors": len(errors),
        "error_rate": len(errors) / max(len(y_true), 1),
        "confusion_pairs": [{"true": a, "pred": b, "count": c} for (a, b), c in pairs.most_common()],
        "false_positives_by_class": dict(fp),
        "false_negatives_by_class": dict(fn),
        "errors": errors[:100],
    }
