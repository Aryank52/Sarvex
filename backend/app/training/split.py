"""Spatial/temporal data split manager to prevent leakage."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np


@dataclass
class SplitManifest:
    strategy: str
    train_indices: list[int]
    val_indices: list[int]
    test_indices: list[int]
    n_total: int
    n_train: int
    n_val: int
    n_test: int
    leakage_checks: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DataSplitManager:
    """Create spatial/temporal/event holdout splits with leakage checks."""

    def __init__(self, seed: int = 42) -> None:
        self.seed = seed

    def spatial_holdout(
        self,
        coordinates: list[tuple[float, float]],
        *,
        test_size: float = 0.2,
        val_size: float = 0.1,
    ) -> SplitManifest:
        # Group by coarse spatial cell to avoid adjacent-pixel leakage.
        rng = np.random.default_rng(self.seed)
        cells = {}
        for i, (x, y) in enumerate(coordinates):
            cell = (round(x, 1), round(y, 1))
            cells.setdefault(cell, []).append(i)
        cell_keys = list(cells.keys())
        rng.shuffle(cell_keys)
        n_test_cells = max(1, int(len(cell_keys) * test_size))
        n_val_cells = max(1, int(len(cell_keys) * val_size))
        test_cells = set(cell_keys[:n_test_cells])
        val_cells = set(cell_keys[n_test_cells : n_test_cells + n_val_cells])
        train_cells = set(cell_keys[n_test_cells + n_val_cells :])
        train_idx = [i for c in train_cells for i in cells[c]]
        val_idx = [i for c in val_cells for i in cells[c]]
        test_idx = [i for c in test_cells for i in cells[c]]
        # leakage check: no cell in multiple splits
        train_set, val_set, test_set = set(train_idx), set(val_idx), set(test_idx)
        leak = {
            "train_val_overlap": bool(train_set & val_set),
            "train_test_overlap": bool(train_set & test_set),
            "val_test_overlap": bool(val_set & test_set),
        }
        return SplitManifest(
            strategy="spatial_holdout",
            train_indices=sorted(train_idx),
            val_indices=sorted(val_idx),
            test_indices=sorted(test_idx),
            n_total=len(coordinates),
            n_train=len(train_idx),
            n_val=len(val_idx),
            n_test=len(test_idx),
            leakage_checks=leak,
        )

    def temporal_holdout(
        self,
        timestamps: list[str],
        *,
        test_fraction: float = 0.2,
        val_fraction: float = 0.1,
    ) -> SplitManifest:
        order = sorted(range(len(timestamps)), key=lambda i: timestamps[i])
        n = len(order)
        n_test = max(1, int(n * test_fraction))
        n_val = max(1, int(n * val_fraction))
        test_idx = order[-n_test:]
        val_idx = order[-(n_test + n_val) : -n_test] if n_val > 0 else []
        train_idx = order[: n - n_test - n_val]
        train_set, val_set, test_set = set(train_idx), set(val_idx), set(test_idx)
        leak = {
            "train_val_overlap": bool(train_set & val_set),
            "train_test_overlap": bool(train_set & test_set),
            "val_test_overlap": bool(val_set & test_set),
            "temporal_order_violation": any(
                timestamps[i] > timestamps[j] for i in train_idx for j in test_idx
            ),
        }
        return SplitManifest(
            strategy="temporal_holdout",
            train_indices=sorted(train_idx),
            val_indices=sorted(val_idx),
            test_indices=sorted(test_idx),
            n_total=n,
            n_train=len(train_idx),
            n_val=len(val_idx),
            n_test=len(test_idx),
            leakage_checks=leak,
        )
