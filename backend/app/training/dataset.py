"""Training dataset builder with label provenance."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np


@dataclass
class TrainingSample:
    sample_id: str
    feature_vector: list[float]
    label: str
    label_type: str  # GOLD | WEAK | PSEUDO
    label_source: str
    label_confidence: float
    observation_id: str | None = None
    dataset_id: str | None = None
    aoi: str | None = None
    timestamp: str | None = None
    event_id: str | None = None
    source_reference: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TrainingDatasetBuilder:
    def __init__(self, feature_names: list[str]) -> None:
        self.feature_names = list(feature_names)
        self.samples: list[TrainingSample] = []

    def add_sample(self, sample: TrainingSample) -> None:
        if len(sample.feature_vector) != len(self.feature_names):
            raise ValueError(
                f"Feature vector length {len(sample.feature_vector)} != {len(self.feature_names)}"
            )
        if sample.label_type not in {"GOLD", "WEAK", "PSEUDO"}:
            raise ValueError(f"Invalid label_type {sample.label_type}")
        self.samples.append(sample)

    def from_arrays(
        self,
        X: np.ndarray,
        y: list[str],
        *,
        label_type: str,
        label_source: str,
        label_confidence: float,
        observation_ids: list[str] | None = None,
        dataset_id: str | None = None,
    ) -> None:
        X = np.asarray(X, dtype="float64")
        for i in range(X.shape[0]):
            self.add_sample(
                TrainingSample(
                    sample_id=f"sample-{len(self.samples):06d}",
                    feature_vector=[float(v) if (v == v) else 0.0 for v in X[i].tolist()],
                    label=str(y[i]),
                    label_type=label_type,
                    label_source=label_source,
                    label_confidence=float(label_confidence),
                    observation_id=(observation_ids[i] if observation_ids else None),
                    dataset_id=dataset_id,
                )
            )

    def summary(self) -> dict[str, Any]:
        from collections import Counter

        label_counts = Counter(s.label for s in self.samples)
        type_counts = Counter(s.label_type for s in self.samples)
        return {
            "n_samples": len(self.samples),
            "n_features": len(self.feature_names),
            "feature_names": self.feature_names,
            "label_counts": dict(label_counts),
            "label_type_counts": dict(type_counts),
            "mean_label_confidence": float(np.mean([s.label_confidence for s in self.samples])) if self.samples else 0.0,
        }

    def to_matrix(self) -> tuple[np.ndarray, list[str], list[str]]:
        X = np.asarray([s.feature_vector for s in self.samples], dtype="float64")
        y = [s.label for s in self.samples]
        ids = [s.sample_id for s in self.samples]
        return X, y, ids

    def save(self, path: str) -> None:
        import json
        from pathlib import Path

        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "feature_names": self.feature_names,
            "samples": [s.to_dict() for s in self.samples],
            "summary": self.summary(),
        }
        p.write_text(json.dumps(payload, indent=2))
