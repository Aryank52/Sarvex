"""Event intelligence: turn measured features into evidence-tiered events.

Events never assert causes. For each feature the factory records:
* event type as a measurement/change category,
* taxonomy stage (DETECTED or CLASSIFIED),
* method + confidence + uncertainty,
* observation links and provenance run,
* contextual links/exposures without overwriting SAR measurements.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.geometry import geometry_area_m2
from app.db.models import (
    AOI,
    AnalysisResult,
    ChangeEvent,
    EventObservationLink,
    Observation,
    Product,
    ProcessingJob,
    ProcessingRun,
    SARFeature,
)
from app.processing.base import FeatureSpec, ProcessorOutput


def _severity(feature: FeatureSpec, confidence: float | None) -> float:
    props = feature.properties or {}
    area = float(props.get("area_m2") or 1.0)
    import math

    area_score = min(max(math.log10(max(area, 1.0)) / 9.0, 0.0), 1.0)  # 1 m2 .. 1000 km2
    mag = abs(float(feature.value or 0.0))
    mag_scale = 10.0 if feature.unit == "mm" else (5.0 if feature.unit == "dB" else max(mag, 1.0))
    mag_score = min(mag / mag_scale, 1.0)
    conf = float(confidence if confidence is not None else feature.confidence or 0.5)
    return float(min(max(0.4 * area_score + 0.35 * conf + 0.25 * mag_score, 0.0), 1.0))


def build_events(
    session: Session,
    *,
    output: ProcessorOutput,
    result: AnalysisResult,
    run: ProcessingRun,
    job: ProcessingJob,
    aoi: AOI | None,
    products: list[Product],
    observations: list[Observation],
    max_events: int = 20,
) -> list[ChangeEvent]:
    features = sorted(
        output.features,
        key=lambda f: float((f.properties or {}).get("area_m2") or 0.0),
        reverse=True,
    )[:max_events]
    events: list[ChangeEvent] = []
    start = min((o.acquisition_start for o in observations if o.acquisition_start), default=None)
    end = max((o.acquisition_start for o in observations if o.acquisition_start), default=None)
    for idx, feature in enumerate(features, start=1):
        props = dict(feature.properties or {})
        conf = feature.confidence if feature.confidence is not None else output.confidence
        severity = _severity(feature, conf)
        area = props.get("area_m2")
        if area is None and feature.geometry:
            try:
                area = geometry_area_m2(feature.geometry)
            except Exception:  # noqa: BLE001
                area = None
        candidate_labels = props.get("candidate_labels") or []
        summary_bits = [
            f"{output.event_type.replace('_', ' ').title()} detected in '{aoi.name if aoi else 'AOI'}'.",
            f"Measured feature: {feature.value:.3f} {feature.unit} (median within component)." if feature.value is not None else "",
            f"Area: {float(area) / 1e6:.3f} km2." if area else "",
            f"Taxonomy stage: {output.taxonomy_stage}. Method: {output.classification_method or output.result_type}.",
        ]
        if candidate_labels:
            summary_bits.append("Candidate labels (hypotheses): " + ", ".join(candidate_labels) + ".")
        summary_bits.append(
            "This is an algorithmic detection, not a causal attribution; independent evidence is required for confirmation."
        )
        event = ChangeEvent(
            event_type=output.event_type,
            taxonomy_stage=output.taxonomy_stage,
            classification_method=output.classification_method,
            classification_confidence=conf,
            geometry=feature.geometry,
            start_time=start,
            end_time=end,
            area_m2=float(area) if area else None,
            magnitude=feature.value,
            magnitude_unit=feature.unit,
            confidence=conf,
            uncertainty=feature.uncertainty,
            persistence=(output.statistics.get("persistence_fraction") if output.statistics else None),
            severity=severity,
            priority=1 if severity >= 0.75 else (2 if severity >= 0.5 else 3),
            status="UNREVIEWED",
            summary=" ".join(bit for bit in summary_bits if bit),
            run_id=run.id,
            model_run_id=None,
            properties={
                "feature_type": feature.feature_type,
                "component_index": idx,
                "algorithm": run.algorithm,
                "algorithm_version": run.algorithm_version,
                "analysis_result_id": result.id,
                "candidate_labels": candidate_labels,
                "feature_properties": props,
                "limitations": output.warnings,
            },
            is_demo=job.is_demo,
        )
        session.add(event)
        session.flush()
        for observation in observations:
            session.add(
                EventObservationLink(event_id=event.id, observation_id=observation.id)
            )
        events.append(event)
    return events


def period_from_job(job: ProcessingJob) -> tuple[datetime | None, datetime | None]:
    return job.time_range_start, job.time_range_end
