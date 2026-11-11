"""Experiment and ablation helpers."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import ExperimentRun


ABLATION_SWITCHES = [
    "USE_L_BAND",
    "USE_S_BAND",
    "USE_POLARIZATION",
    "USE_TEMPORAL",
    "USE_CONTEXT",
    "USE_COHERENCE",
    "USE_INSAR",
    "USE_ML",
    "USE_DEEP_MODEL",
]


def record_experiment(
    session: Session,
    *,
    experiment_id: str,
    hypothesis: str | None = None,
    dataset_version: str | None = None,
    baseline: str | None = None,
    candidate_model: str | None = None,
    parameters: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    result_artifact: str | None = None,
    status: str = "COMPLETED",
) -> ExperimentRun:
    run = ExperimentRun(
        experiment_id=experiment_id,
        hypothesis=hypothesis,
        dataset_version=dataset_version,
        baseline=baseline,
        candidate_model=candidate_model,
        parameters=parameters or {},
        metrics=metrics or {},
        result_artifact=result_artifact,
        status=status,
    )
    session.add(run)
    session.commit()
    return run
