import { useMemo } from "react";
import { Link } from "react-router-dom";
import type {
  Capabilities,
  EventFeatureCollection,
  EventStats,
  EventSummary,
  Health,
  Page,
  ResultSummary,
} from "../api/types";
import { useApi } from "../hooks/useApi";
import { formatArea, formatDate, formatNumber, titleCase } from "../lib/format";
import { MapView } from "../components/MapView";
import {
  DemoTag,
  ErrorState,
  Kpi,
  LoadingBlock,
  SectionHeader,
  StageBadge,
  StatusBadge,
} from "../components/States";

const PIPELINE = [
  { key: "ingest", label: "Ingest", copy: "Validated products, immutable manifests" },
  { key: "process", label: "Process", copy: "SAR, InSAR, polarimetric, temporal" },
  { key: "detect", label: "Detect", copy: "Robust statistics with uncertainty" },
  { key: "evidence", label: "Evidence", copy: "Staged, citable, independently gated" },
  { key: "explain", label: "Explain", copy: "Grounded RAG and copilot" },
];

export function Dashboard() {
  const health = useApi<Health>("/health");
  const stats = useApi<EventStats>("/events/stats");
  const events = useApi<Page<EventSummary>>("/events?limit=5");
  const geojson = useApi<EventFeatureCollection>("/events/geojson?limit=300");
  const results = useApi<Page<ResultSummary>>("/results?limit=6");
  const capabilities = useApi<Capabilities>("/capabilities");

  const topTypes = useMemo(() => {
    const entries = Object.entries(stats.data?.by_type || {}).sort((a, b) => b[1] - a[1]);
    const max = entries[0]?.[1] || 1;
    return entries.map(([type, count]) => ({ type, count, fraction: count / max }));
  }, [stats.data]);

  return (
    <div className="page-stack">
      <section className="hero">
        <div className="hero-copy">
          <div className="kicker">NASA Space Apps · Dancing with the SARs</div>
          <h1>
            See the change.
            <br />
            <span>Show the evidence.</span>
          </h1>
          <p>
            SARVEX turns NISAR-family radar products into measured surface-change intelligence —
            with units, uncertainty and provenance attached to every claim. Explanations are
            grounded; confirmation requires independent evidence.
          </p>
          <div className="hero-actions">
            <Link className="btn btn-primary" to="/explore">
              Explore the map
            </Link>
            <Link className="btn btn-ghost" to="/copilot">
              Ask the copilot
            </Link>
            <Link className="btn btn-quiet" to="/method">
              Read the method
            </Link>
          </div>
          <div className="hero-note">
            <span className="pulse-dot" />
            {health.data
              ? `${health.data.demo_mode.effective_data_mode} data mode · ${health.data.database.backend} · ${health.data.worker.mode.replaceAll("_", " ")}`
              : "Connecting to the SARVEX engine"}
          </div>
        </div>

        <div className="hero-panel">
          <div className="hero-panel-head">
            <span>Operational chain</span>
            <span className="mono">{health.data?.code_version || "sarvex-1.0"}</span>
          </div>
          <div className="pipeline">
            {PIPELINE.map((step, index) => (
              <div className="pipeline-step" key={step.key}>
                <span className="pipeline-index">{String(index + 1).padStart(2, "0")}</span>
                <div>
                  <strong>{step.label}</strong>
                  <small>{step.copy}</small>
                </div>
                <span className="pipeline-check">●</span>
              </div>
            ))}
          </div>
          <div className="hero-panel-foot">
            <span>DB {health.data?.database.backend || "…"}</span>
            <span>ISCE3 {health.data?.isce3.available ? "available" : "not installed"}</span>
            <span>RAG {health.data?.rag.documents ?? "…"} docs</span>
          </div>
        </div>
      </section>

      {health.error ? <ErrorState error={health.error} retry={health.reload} /> : null}

      <div className="kpi-grid">
        <Kpi
          label="Detected events"
          value={stats.data ? formatNumber(stats.data.total, 0) : "…"}
          detail={`${stats.data?.demo ?? 0} synthetic demo fixtures · staged, not hazard claims`}
          tone="amber"
        />
        <Kpi
          label="Analysis results"
          value={results.data ? formatNumber(results.data.total, 0) : "…"}
          detail="Every result carries algorithm, units and provenance"
          tone="cyan"
        />
        <Kpi
          label="Knowledge passages"
          value={health.data ? formatNumber(health.data.rag.chunks, 0) : "…"}
          detail={`${health.data?.rag.documents ?? 0} documents · citations stay attached`}
          tone="violet"
        />
        <Kpi
          label="Demo products"
          value={health.data ? formatNumber(health.data.demo_mode.demo_products, 0) : "…"}
          detail="Synthetic fixtures, explicitly labelled end to end"
          tone="green"
        />
      </div>

      <div className="dashboard-grid">
        <section className="panel panel-map">
          <div className="panel-head">
            <div>
              <div className="kicker">Spatial evidence</div>
              <h2>Surface-change event map</h2>
            </div>
            <Link className="text-link" to="/explore">
              Open full explorer →
            </Link>
          </div>
          {geojson.error ? (
            <ErrorState error={geojson.error} retry={geojson.reload} />
          ) : geojson.data ? (
            <MapView events={geojson.data} height={440} />
          ) : (
            <LoadingBlock label="Loading event geometry" rows={4} />
          )}
          <div className="map-caption">
            <span>
              {geojson.data?.metadata.count ?? 0} geometries · evidence stage colour-coded
            </span>
            <span>{geojson.data?.metadata.notice || "Geometry from measured analysis outputs"}</span>
          </div>
        </section>

        <aside className="panel">
          <div className="panel-head">
            <div>
              <div className="kicker">Review queue</div>
              <h2>Recent events</h2>
            </div>
            <Link className="text-link" to="/events">
              All events →
            </Link>
          </div>
          {events.error ? (
            <ErrorState error={events.error} retry={events.reload} />
          ) : events.loading ? (
            <LoadingBlock label="Loading events" />
          ) : events.data?.items.length ? (
            <div className="event-mini-list">
              {events.data.items.map((event) => (
                <Link className="event-mini" key={event.id} to={`/events?event=${event.id}`}>
                  <div className="event-mini-top">
                    <StageBadge stage={event.taxonomy_stage} />
                    <StatusBadge status={event.status} />
                    {event.is_demo ? <DemoTag /> : null}
                  </div>
                  <div className="event-mini-title">{titleCase(event.event_type)}</div>
                  <p>{event.summary}</p>
                  <div className="event-mini-meta">
                    <span>{formatArea(event.area_m2)}</span>
                    <span>{formatDate(event.start_time)}</span>
                    <span>
                      {event.magnitude !== null
                        ? `${formatNumber(event.magnitude, 2)} ${event.magnitude_unit || ""}`
                        : "no magnitude"}
                    </span>
                  </div>
                </Link>
              ))}
            </div>
          ) : (
            <div className="empty-state compact">No events yet. Run an analysis to detect change.</div>
          )}
          <div className="type-bars">
            <div className="finding-label">Event mix</div>
            {topTypes.length ? (
              topTypes.map((item) => (
                <div className="type-bar" key={item.type}>
                  <span>{titleCase(item.type)}</span>
                  <div>
                    <i style={{ width: `${Math.max(item.fraction * 100, 4)}%` }} />
                  </div>
                  <b>{item.count}</b>
                </div>
              ))
            ) : (
              <p className="muted">No classification data yet.</p>
            )}
          </div>
        </aside>
      </div>

      <div className="dashboard-grid dashboard-grid-even">
        <section className="panel">
          <div className="panel-head">
            <div>
              <div className="kicker">Measured outputs</div>
              <h2>Latest analyses</h2>
            </div>
            <Link className="text-link" to="/analyses">
              New analysis →
            </Link>
          </div>
          {results.error ? (
            <ErrorState error={results.error} retry={results.reload} />
          ) : results.loading ? (
            <LoadingBlock label="Loading results" />
          ) : results.data?.items.length ? (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Analysis</th>
                    <th>Units</th>
                    <th>Confidence</th>
                    <th>Created</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {results.data.items.map((result) => (
                    <tr key={result.id}>
                      <td>
                        <Link to={`/analyses/${result.id}`}>{titleCase(result.result_type)}</Link>
                        {result.is_demo ? <DemoTag /> : null}
                      </td>
                      <td>{result.units || "—"}</td>
                      <td>
                        {result.confidence !== null
                          ? `${formatNumber(result.confidence * 100, 0)}%`
                          : "—"}
                      </td>
                      <td>{formatDate(result.created_at)}</td>
                      <td>
                        <Link className="row-link" to={`/analyses/${result.id}`}>
                          Open
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="empty-state compact">No analyses have been run yet.</div>
          )}
        </section>

        <section className="panel capability-panel">
          <div className="panel-head">
            <div>
              <div className="kicker">Declared capabilities</div>
              <h2>What SARVEX can measure</h2>
            </div>
            <Link className="text-link" to="/method">
              Guardrails →
            </Link>
          </div>
          <div className="capability-list">
            {capabilities.data?.analysis_types.map((item) => (
              <div className="capability" key={item.type}>
                <div className="capability-type">{titleCase(item.type)}</div>
                <div className="capability-modes">
                  {item.modes.map((mode) => (
                    <span key={mode}>{mode}</span>
                  ))}
                </div>
                <div className="capability-min">min {item.min_products} product{item.min_products > 1 ? "s" : ""}</div>
              </div>
            )) || <LoadingBlock label="Loading capabilities" rows={4} />}
          </div>
          <div className="guardrail-note">
            <strong>No model is hard-coded.</strong> Embeddings, reranker and language models are
            resolved through the model registry; offline-safe defaults keep the platform honest
            when providers are absent.
          </div>
          <div className="integrity-grid">
            <div>
              <span>Database</span>
              <strong>{health.data ? health.data.database.backend : "…"}</strong>
            </div>
            <div>
              <span>Objects</span>
              <strong>{health.data?.object_storage.backend || "…"}</strong>
            </div>
            <div>
              <span>Worker</span>
              <strong>{health.data?.worker.inline ? "inline" : "external"}</strong>
            </div>
            <div>
              <span>Providers</span>
              <strong>{health.data?.offline_mode ? "offline-safe" : "network"}</strong>
            </div>
          </div>
        </section>
      </div>

      <SectionHeader
        kicker="Evidence discipline"
        title="A claim is only as strong as its stage"
        description="SARVEX never upgrades a detection to a confirmation without independent external evidence. Each stage is visible in the API, the UI and generated reports."
      />
      <div className="stage-ladder">
        {[
          ["OBSERVED", "Instrument values as measured."],
          ["DERIVED", "Quantities computed from observations."],
          ["DETECTED", "Regions flagged by a stated algorithm."],
          ["CLASSIFIED", "Rule or model labels; still unconfirmed."],
          ["HYPOTHESIZED", "Explanations requiring validation."],
          ["CONTEXTUALIZED", "Related context; proximity is not causality."],
          ["CONFIRMED", "Independent authoritative evidence attached."],
        ].map(([stage, copy], index) => (
          <div className="ladder-step" key={stage}>
            <span className="ladder-index">{index + 1}</span>
            <StageBadge stage={stage} />
            <p>{copy}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
