"""Analysis and event report generation.

Reports are explicitly scientific: measurements, sources, methods, models,
uncertainty, provenance, attribution and limitations. Inferred interpretations
are labelled and never presented as facts.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.core.taxonomy import STAGE_DESCRIPTIONS, EvidenceStage
from app.db.models import (
    AOI,
    AnalysisResult,
    ChangeEvent,
    Dataset,
    EventExposure,
    GeospatialContext,
    InfrastructureAsset,
    ModelRun,
    Observation,
    ProcessingJob,
    ProcessingRun,
    Product,
    Report,
)
from app.schemas.knowledge import ReportCreate
from app.storage.object_store import get_object_store


def _fmt(value: float | None, unit: str | None = None, digits: int = 3) -> str:
    if value is None:
        return "not available"
    text = f"{value:,.{digits}f}"
    return f"{text} {unit}" if unit else text


def _dt(value: datetime | None) -> str:
    if not value:
        return "not available"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _result_report(session: Session, result: AnalysisResult, title: str | None) -> tuple[str, str, dict[str, Any]]:
    run = session.get(ProcessingRun, result.run_id)
    job = session.get(ProcessingJob, run.job_id) if run else None
    aoi = session.get(AOI, result.aoi_id) if result.aoi_id else None
    products: list[Product] = []
    observations: list[Observation] = []
    datasets: list[Dataset] = []
    if run:
        products = session.scalars(select(Product).where(Product.id.in_(run.input_product_ids or [""]))).all()
        observations = session.scalars(select(Observation).where(Observation.id.in_(run.observation_ids or [""]))).all()
        datasets = session.scalars(select(Dataset).where(Dataset.id.in_([o.dataset_id for o in observations] or [""]))).all()
    events = session.scalars(select(ChangeEvent).where(ChangeEvent.run_id == run.id)).all() if run else []
    model_runs = session.scalars(
        select(ModelRun).where(
            ModelRun.correlation_id == (job.correlation_id if job else None)
        )
    ).all() if job else []

    stats = result.statistics or {}
    lines: list[str] = []
    lines.append(f"# {title or 'SARVEX Analysis Report'}")
    lines.append("")
    if result.is_demo:
        lines.append(
            "> **DEMO MODE — SYNTHETIC FIXTURES.** This report was generated from SARVEX "
            "synthetic demo data. It is **not** a NASA or ISRO NISAR observation and must not "
            "be cited as one."
        )
        lines.append("")
    lines.append("## 1. Analysis summary")
    lines.append("")
    lines.append(result.summary or "No summary recorded.")
    lines.append("")
    lines.append("## 2. Area of interest")
    lines.append("")
    if aoi:
        lines.append(f"- **Name:** {aoi.name}")
        lines.append(f"- **CRS:** {aoi.crs}")
        lines.append(f"- **Bounding box:** {aoi.bbox}")
        lines.append(f"- **Geodesic area:** {_fmt(aoi.area_m2, 'm²', 0)}")
        lines.append(f"- **Description:** {aoi.description or 'not provided'}")
    else:
        lines.append("AOI metadata not available.")
    lines.append("")
    lines.append("## 3. Data sources and products")
    lines.append("")
    lines.append("| Product | Type | Provider | Acquisition (UTC) | Band | Polarization | Demo |")
    lines.append("|---|---|---|---|---|---|---|")
    for product in products:
        obs = product.observation
        lines.append(
            f"| `{product.product_id}` | {product.product_type} | {product.provider} | "
            f"{_dt(obs.acquisition_start) if obs else 'n/a'} | "
            f"{obs.frequency_band if obs else 'n/a'} | "
            f"{obs.polarization if obs else 'n/a'} | "
            f"{'YES' if product.is_demo else 'no'} |"
        )
    lines.append("")
    if datasets:
        lines.append("Datasets and attribution:")
        lines.append("")
        for dataset in datasets:
            lines.append(f"- `{dataset.dataset_id}` — {dataset.provider}; license: {dataset.license or 'unspecified'}")
            if dataset.citation:
                lines.append(f"  - Citation: {dataset.citation}")
        lines.append("")
    lines.append("## 4. Processing method and reproducibility")
    lines.append("")
    if run:
        lines.append(f"- **Algorithm:** {run.algorithm} (version {run.algorithm_version})")
        lines.append(f"- **Result type:** {result.result_type}")
        lines.append(f"- **Units:** {result.units or 'not specified'}")
        lines.append(f"- **CRS:** {run.crs}")
        lines.append(f"- **Code version:** `{run.code_version}`")
        lines.append(f"- **Run started:** {_dt(run.started_at)}")
        lines.append(f"- **Run finished:** {_dt(run.finished_at)}")
        lines.append(f"- **Parameters:** `{run.parameters}`")
        lines.append(f"- **Dataset IDs:** {', '.join(run.dataset_ids) or 'n/a'}")
        lines.append(f"- **Observation IDs:** {', '.join(run.observation_ids) or 'n/a'}")
        lines.append(
            f"- **Model:** {run.model_name or 'deterministic algorithm'} "
            f"{('@ ' + run.model_version) if run.model_version else ''}"
        )
        lines.append("")
        lines.append("Provenance record:")
        lines.append("")
        lines.append("```json")
        import json

        lines.append(json.dumps(run.provenance, indent=2, default=str)[:8000])
        lines.append("```")
    else:
        lines.append("Processing run metadata not available.")
    lines.append("")
    lines.append("## 5. Measurements and statistics")
    lines.append("")
    lines.append(f"- **Confidence:** {_fmt(result.confidence, 'unitless', 3)} (detection confidence, not hazard probability)")
    lines.append(f"- **Uncertainty:** {_fmt(result.uncertainty, result.units, 3)}")
    lines.append("")
    lines.append("| Statistic | Value |")
    lines.append("|---|---|")
    for key in sorted(stats):
        value = stats[key]
        if isinstance(value, (dict, list)):
            continue
        if isinstance(value, float):
            value = f"{value:,.4f}"
        lines.append(f"| {key} | {value} |")
    lines.append("")
    lines.append("## 6. Detected events")
    lines.append("")
    if events:
        lines.append("| Event | Type | Stage | Magnitude | Area (km²) | Confidence | Status |")
        lines.append("|---|---|---|---|---|---|---|")
        for event in events:
            lines.append(
                f"| `{event.id[:8]}` | {event.event_type} | {event.taxonomy_stage} | "
                f"{_fmt(event.magnitude, event.magnitude_unit)} | "
                f"{_fmt((event.area_m2 or 0) / 1e6, 'km²', 4)} | "
                f"{_fmt(event.confidence, None, 2)} | {event.status} |"
            )
    else:
        lines.append("No events met the configured detection thresholds.")
    lines.append("")
    lines.append("## 7. Layered outputs")
    lines.append("")
    for name, meta in (result.layer_metadata or {}).items():
        if isinstance(meta, dict) and meta.get("title"):
            lines.append(
                f"- **{meta['title']}** (`{name}`) — units: {meta.get('units')}; "
                f"method: {meta.get('method')}; source: {meta.get('source')}"
            )
    lines.append("")
    lines.append("## 8. Model and copilot runs")
    lines.append("")
    if model_runs:
        for run_record in model_runs:
            lines.append(
                f"- {run_record.purpose}: {run_record.model_name}@{run_record.model_version} "
                f"({run_record.status}, {run_record.latency_ms or 0:.0f} ms)"
            )
    else:
        lines.append("No model runs are associated with this analysis.")
    lines.append("")
    lines.append("## 9. Interpretation and limitations")
    lines.append("")
    lines.append(
        "Measurements above are **OBSERVED** or **DERIVED** from the input products. "
        "Detected regions are **DETECTED** by the stated algorithm. No causal attribution is made. "
        "A detected change is not an earthquake, flood, landslide or eruption without independent evidence."
    )
    lines.append("")
    for limitation in (result.layer_metadata or {}).get("limitations", []) or []:
        lines.append(f"- {limitation}")
    limitations = [
        "SAR measurements are relative unless an absolute reference is established.",
        "Detection thresholds are configuration choices; results should be tested for sensitivity.",
        "Context and exposure analysis indicates spatial proximity, never confirmed damage.",
    ]
    for limitation in limitations:
        lines.append(f"- {limitation}")
    lines.append("")
    lines.append("## 10. Attribution")
    lines.append("")
    lines.append(
        "Data attribution follows the provider records in section 3. "
        "Where products are demo fixtures, the data are synthetic SARVEX data and are not NASA/ISRO observations."
    )
    lines.append("")
    lines.append(f"_Report generated {_dt(datetime.now(timezone.utc))} by SARVEX._")
    provenance = {
        "result_id": result.id,
        "run_id": result.run_id,
        "code_version": run.code_version if run else None,
        "algorithm": run.algorithm if run else None,
        "algorithm_version": run.algorithm_version if run else None,
        "demo": result.is_demo,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    return "\n".join(lines), f"SARVEX Analysis Report — {result.result_type}", provenance


def _event_report(session: Session, event: ChangeEvent, title: str | None) -> tuple[str, str, dict[str, Any]]:
    run = session.get(ProcessingRun, event.run_id) if event.run_id else None
    result = None
    if run:
        result = session.scalar(select(AnalysisResult).where(AnalysisResult.run_id == run.id))
    exposures = session.scalars(select(EventExposure).where(EventExposure.event_id == event.id)).all()
    assets = {
        a.id: a
        for a in session.scalars(
            select(InfrastructureAsset).where(InfrastructureAsset.id.in_([e.asset_id for e in exposures] or [""]))
        ).all()
    }
    contexts = []
    for link in event.context_links:
        ctx = session.get(GeospatialContext, link.context_id)
        if ctx:
            contexts.append((ctx, link.relation))
    lines = [f"# {title or 'SARVEX Change Event Report'}", ""]
    if event.is_demo:
        lines.append(
            "> **DEMO MODE — SYNTHETIC FIXTURES.** This event was derived from SARVEX synthetic "
            "demo data, not NASA/ISRO observations."
        )
        lines.append("")
    lines.append("## Event")
    lines.append("")
    lines.append(f"- **Event ID:** `{event.id}`")
    lines.append(f"- **Category:** {event.event_type}")
    lines.append(f"- **Taxonomy stage:** {event.taxonomy_stage} — {STAGE_DESCRIPTIONS.get(EvidenceStage(event.taxonomy_stage), '')}")
    lines.append(f"- **Method:** {event.classification_method or 'not recorded'}")
    lines.append(f"- **Start / end (UTC):** {_dt(event.start_time)} / {_dt(event.end_time)}")
    lines.append(f"- **Magnitude:** {_fmt(event.magnitude, event.magnitude_unit)}")
    lines.append(f"- **Area:** {_fmt((event.area_m2 or 0) / 1e6, 'km²', 4)}")
    lines.append(f"- **Confidence:** {_fmt(event.confidence, None, 3)}")
    lines.append(f"- **Uncertainty:** {_fmt(event.uncertainty, event.magnitude_unit, 3)}")
    lines.append(f"- **Persistence:** {_fmt(event.persistence, None, 3)}")
    lines.append(f"- **Severity (rule-based):** {_fmt(event.severity, None, 3)}")
    lines.append(f"- **Status:** {event.status}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(event.summary or "No summary recorded.")
    lines.append("")
    if result:
        lines.append("## Parent analysis")
        lines.append("")
        lines.append(result.summary)
        lines.append("")
        lines.append(f"- Analysis units: {result.units}")
        lines.append(f"- Analysis confidence: {_fmt(result.confidence, None, 3)}")
        lines.append(f"- Analysis uncertainty: {_fmt(result.uncertainty, result.units, 3)}")
        lines.append("")
    lines.append("## Context correlation")
    lines.append("")
    if contexts:
        for ctx, relation in contexts:
            lines.append(
                f"- **{ctx.name}** ({ctx.layer_type}, {relation}) — provider: {ctx.provider}; "
                f"license: {ctx.license}; source: {ctx.source}"
            )
    else:
        lines.append("No context layers intersect or lie near this event.")
    lines.append("")
    lines.append("## Potential exposure")
    lines.append("")
    if exposures:
        lines.append("| Asset | Type | Distance (m) | Overlap ratio | Exposure score |")
        lines.append("|---|---|---|---|---|")
        for exposure in exposures:
            asset = assets.get(exposure.asset_id)
            lines.append(
                f"| {asset.name if asset else exposure.asset_id} | "
                f"{asset.asset_type if asset else 'n/a'} | {exposure.distance_m:,.0f} | "
                f"{exposure.overlap_ratio:.2f} | {exposure.exposure_score:.3f} |"
            )
        lines.append("")
        lines.append(
            "Exposure means **potential spatial proximity**, not observed damage. "
            "Damage assessment requires independent evidence."
        )
    else:
        lines.append("No infrastructure assets lie within the exposure distance threshold.")
    lines.append("")
    lines.append("## Provenance")
    lines.append("")
    if run:
        lines.append("```json")
        import json

        lines.append(json.dumps(run.provenance, indent=2, default=str)[:8000])
        lines.append("```")
    else:
        lines.append("No processing run is linked to this event.")
    lines.append("")
    lines.append("## Limitations")
    lines.append("")
    lines.append(
        "This event is an algorithmic detection. Category assignment is rule-based and does not establish "
        "a physical mechanism. Confirmation requires independent authoritative evidence (for example seismic "
        "records, gauge measurements or field validation)."
    )
    lines.append("")
    provenance = {
        "event_id": event.id,
        "run_id": event.run_id,
        "taxonomy_stage": event.taxonomy_stage,
        "demo": event.is_demo,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    return "\n".join(lines), f"SARVEX Change Event Report — {event.event_type}", provenance


def create_report(session: Session, request: ReportCreate) -> Report:
    if not request.result_id and not request.event_id:
        raise ValidationError("A result_id or event_id is required")
    if request.result_id:
        result = session.get(AnalysisResult, request.result_id)
        if not result:
            raise NotFoundError(f"Analysis result {request.result_id} not found")
        markdown, default_title, provenance = _result_report(session, result, request.title)
    else:
        event = session.get(ChangeEvent, request.event_id)
        if not event:
            raise NotFoundError(f"Change event {request.event_id} not found")
        markdown, default_title, provenance = _event_report(session, event, request.title)
    if request.format == "html":
        try:
            import markdown as markdown_lib

            html_body = markdown_lib.markdown(
                markdown, extensions=["tables", "fenced_code", "toc"]
            )
        except ImportError:
            html_body = f"<pre>{markdown}</pre>"
        content = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            f"<title>{default_title}</title>"
            "<style>body{font-family:Georgia,serif;max-width:900px;margin:40px auto;line-height:1.5;color:#1b1f24}"
            "table{border-collapse:collapse;width:100%;margin:1rem 0}td,th{border:1px solid #ccd;padding:6px 9px;text-align:left}"
            "code{background:#eef1f5;padding:1px 4px}pre{background:#f4f6f8;padding:12px;overflow:auto}"
            "blockquote{border-left:4px solid #d9822b;margin-left:0;padding-left:14px;color:#5a4630}</style>"
            f"</head><body>{html_body}</body></html>"
        )
        extension = "html"
        content_type = "text/html"
    else:
        content = markdown
        extension = "md"
        content_type = "text/markdown"
    report = Report(
        title=default_title[:400],
        report_type="EVENT" if request.event_id else "ANALYSIS",
        result_id=request.result_id,
        event_id=request.event_id,
        format=request.format,
        content=content,
        provenance=provenance,
    )
    session.add(report)
    session.flush()
    store = get_object_store()
    uri = store.put_bytes(
        f"reports/{report.id}/report.{extension}",
        content.encode("utf-8"),
        content_type,
    )
    report.artifact_uri = uri
    session.commit()
    return report


def get_report_content(session: Session, report_id: str) -> tuple[Report, bytes, str]:
    report = session.get(Report, report_id)
    if not report:
        raise NotFoundError(f"Report {report_id} not found")
    if report.artifact_uri:
        store = get_object_store()
        return report, store.get_bytes(report.artifact_uri), "text/html" if report.format == "html" else "text/markdown"
    return report, report.content.encode("utf-8"), "text/plain"
