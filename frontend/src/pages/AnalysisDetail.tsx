import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, layerGeoTiffUrl, layerPngUrl, post, reportDownloadUrl } from "../api/client";
import type {
  EventFeatureCollection,
  Feature,
  LayersResponse,
  Report,
  ResultDetail,
  TimeSeries,
} from "../api/types";
import { useApi } from "../hooks/useApi";
import {
  formatArea,
  formatDate,
  formatNumber,
  formatPercent,
  titleCase,
} from "../lib/format";
import { MapView, type MapLayer } from "../components/MapView";
import { Sparkline } from "../components/Sparkline";
import { CopilotPanel } from "../components/CopilotPanel";
import {
  Confidence,
  DemoTag,
  ErrorState,
  LoadingBlock,
  SectionHeader,
  StageBadge,
  StatusBadge,
} from "../components/States";

const LAYER_PRIORITY = ["difference", "displacement", "ratio_change", "confidence", "coherence", "before"];

function pickLayer(layers: LayersResponse): string | null {
  if (!layers.layers.length) return null;
  for (const name of LAYER_PRIORITY) {
    if (layers.layers.some((layer) => layer.name === name)) return name;
  }
  return layers.layers[0].name;
}

function StatValue({ value, units }: { value: unknown; units: string | null }) {
  if (typeof value === "boolean") return <>{value ? "yes" : "no"}</>;
  if (typeof value === "number") {
    return (
      <>
        {formatNumber(value, Math.abs(value) < 0.01 ? 5 : 3)}
        {units ? <span className="stat-unit"> {units}</span> : null}
      </>
    );
  }
  if (typeof value === "string") return <>{value}</>;
  if (value === null || value === undefined) return <>—</>;
  return <code className="inline-json">{JSON.stringify(value)}</code>;
}

function unitForKey(key: string): string | null {
  if (key.endsWith("_db")) return "dB";
  if (key.endsWith("_mm")) return "mm";
  if (key.endsWith("_km2")) return "km²";
  if (key.endsWith("_m2")) return "m²";
  if (key.endsWith("_m")) return "m";
  if (key.endsWith("_px")) return "px";
  if (key.endsWith("_hz")) return "Hz";
  return null;
}

export function AnalysisDetail() {
  const { resultId = "" } = useParams();
  const detail = useApi<ResultDetail>(resultId ? `/results/${resultId}` : null);
  const layers = useApi<LayersResponse>(resultId ? `/results/${resultId}/layers` : null);
  const timeseries = useApi<TimeSeries[]>(resultId ? `/results/${resultId}/timeseries` : null);
  const hfce = useApi<{
    available: boolean;
    prediction?: {
      event_type: string;
      change_probability: number;
      confidence: number;
      uncertainty: number;
      top_features: { feature: string; importance?: number; value?: unknown }[];
      baseline_score: number;
      ml_score: number;
      anomaly_score: number;
    };
    caveat?: string;
  }>(resultId ? `/results/${resultId}/hfce` : null);
  const features = useApi<Feature[]>(resultId ? `/results/${resultId}/features` : null);
  const [selectedLayer, setSelectedLayer] = useState<string | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [reportBusy, setReportBusy] = useState<string | null>(null);
  const [reportError, setReportError] = useState<string | null>(null);

  useEffect(() => {
    if (!layers.data) return;
    const available = layers.data.layers.map((layer) => layer.name);
    if (!selectedLayer || !available.includes(selectedLayer)) {
      setSelectedLayer(pickLayer(layers.data));
    }
  }, [layers.data, selectedLayer]);

  const meta = layers.data?.layers.find((layer) => layer.name === selectedLayer) || null;
  const mapLayer: MapLayer | null = useMemo(() => {
    if (!resultId || !meta) return null;
    return {
      url: layerPngUrl(resultId, meta.name),
      coordinates: meta.image_coordinates,
      name: meta.name,
    };
  }, [resultId, meta]);

  const eventCollection: EventFeatureCollection | null = useMemo(() => {
    if (!detail.data?.events.length) return null;
    return {
      type: "FeatureCollection",
      features: detail.data.events.map((event) => ({
        type: "Feature",
        id: event.id,
        geometry: event.geometry,
        properties: {
          event_type: event.event_type,
          taxonomy_stage: event.taxonomy_stage,
          status: event.status,
          confidence: event.confidence,
          uncertainty: event.uncertainty,
          area_m2: event.area_m2,
          magnitude: event.magnitude,
          magnitude_unit: event.magnitude_unit,
          severity: event.severity,
          priority: event.priority,
          summary: event.summary,
          is_demo: event.is_demo,
          start_time: event.start_time,
          end_time: event.end_time,
        },
      })),
      metadata: {
        count: detail.data.events.length,
        demo_mode: detail.data.events.some((event) => event.is_demo),
        notice: detail.data.events.some((event) => event.is_demo)
          ? "Synthetic SARVEX fixtures — not NASA/ISRO observations."
          : null,
      },
    };
  }, [detail.data]);

  const statisticEntries = useMemo(() => {
    const stats = detail.data?.statistics || {};
    return Object.entries(stats)
      .filter(([, value]) => ["string", "number", "boolean"].includes(typeof value))
      .slice(0, 24);
  }, [detail.data]);

  async function generateReport(format: "markdown" | "html") {
    if (!resultId) return;
    setReportBusy(format);
    setReportError(null);
    try {
      const response = await post<Report>("/reports", {
        result_id: resultId,
        format,
        title: `SARVEX ${detail.data?.result_type || "analysis"} report`,
      });
      setReport(response);
    } catch (error) {
      setReportError(error instanceof ApiError ? error.message : "Report generation failed.");
    } finally {
      setReportBusy(null);
    }
  }

  if (detail.error) {
    return (
      <div className="page-stack">
        <SectionHeader kicker="Analysis detail" title="Result unavailable" />
        <ErrorState error={detail.error} retry={detail.reload} />
        <Link className="btn btn-ghost" to="/analyses">Back to analyses</Link>
      </div>
    );
  }

  if (!detail.data) {
    return (
      <div className="page-stack">
        <SectionHeader kicker="Analysis detail" title="Loading measured result" />
        <LoadingBlock label="Loading result" rows={6} />
      </div>
    );
  }

  const result = detail.data;

  return (
    <div className="page-stack">
      <SectionHeader
        kicker="Measured result"
        title={titleCase(result.result_type)}
        description={result.summary}
        actions={
          <>
            <Link className="btn btn-ghost" to="/analyses">All analyses</Link>
            <button
              className="btn btn-primary"
              onClick={() => void generateReport("markdown")}
              disabled={reportBusy !== null}
            >
              {reportBusy === "markdown" ? "Generating…" : "Generate report"}
            </button>
          </>
        }
      />

      <div className="detail-badges">
        <span className="result-id mono">{result.id}</span>
        {result.is_demo ? <DemoTag /> : null}
        <span className="mode-pill mode-demo">{result.units || "unitless"}</span>
        <Confidence value={result.confidence} />
        <span className="muted">uncertainty {formatNumber(result.uncertainty, 3)} {result.units || ""}</span>
        <span className="muted">created {formatDate(result.created_at, true)}</span>
      </div>

      {result.is_demo ? (
        <div className="inline-warning">
          This result was computed from SARVEX synthetic fixtures. It demonstrates the processing
          chain and is not an observation of the real Assam AOI.
        </div>
      ) : null}

      {reportError ? <div className="inline-notice notice-error">{reportError}</div> : null}
      {report ? (
        <div className="inline-notice notice-ok">
          {report.format.toUpperCase()} report generated ·{" "}
          <a href={reportDownloadUrl(report.id)} target="_blank" rel="noreferrer">
            download report ↗
          </a>
        </div>
      ) : null}

      <div className="analysis-detail-grid">
        <section className="panel map-panel">
          <div className="panel-head">
            <div>
              <div className="kicker">Georeferenced output</div>
              <h2>{meta?.title || "Layer preview"}</h2>
            </div>
            {meta ? (
              <a className="text-link" href={layerPngUrl(result.id, meta.name)} target="_blank" rel="noreferrer">
                Raw PNG ↗
              </a>
            ) : null}
          </div>

          {eventCollection ? <MapView events={eventCollection} layer={mapLayer} height={480} /> : null}
          {!eventCollection && mapLayer ? <MapView layer={mapLayer} height={480} /> : null}
          {!eventCollection && !mapLayer ? <div className="map-placeholder">No spatial layer is available for this result.</div> : null}

          <div className="layer-strip">
            {layers.data?.layers.map((layer) => (
              <button
                key={layer.name}
                className={`layer-chip${selectedLayer === layer.name ? " active" : ""}`}
                onClick={() => setSelectedLayer(layer.name)}
              >
                <span
                  className="ramp"
                  style={{ background: `linear-gradient(90deg, ${layer.legend.map((stop) => stop.color).join(",")})` }}
                />
                <span>
                  <strong>{layer.title}</strong>
                  <small>{layer.units} · {layer.method}</small>
                </span>
              </button>
            )) || null}
          </div>

          {meta ? (
            <div className="layer-downloads">
              <a className="btn btn-sm btn-ghost" href={layerGeoTiffUrl(result.id, meta.name)} download>
                Download GeoTIFF
              </a>
              <span className="fine-print">
                {meta.width} × {meta.height} px · {meta.crs} · valid {formatPercent(meta.valid_fraction)}
              </span>
            </div>
          ) : null}
        </section>

        <aside className="panel detail-card">
          <div className="kicker">Result metadata</div>
          <h2>What was measured</h2>
          <div className="stat-grid stat-grid-compact">
            <div>
              <span>Units</span>
              <strong>{result.units || "—"}</strong>
            </div>
            <div>
              <span>Confidence</span>
              <strong>{result.confidence !== null ? formatPercent(result.confidence) : "—"}</strong>
            </div>
            <div>
              <span>Uncertainty</span>
              <strong>{formatNumber(result.uncertainty, 3)}</strong>
            </div>
            <div>
              <span>Events emitted</span>
              <strong>{result.events.length}</strong>
            </div>
            <div>
              <span>AOI</span>
              <strong className="mono small">{result.aoi_id ? result.aoi_id.slice(0, 10) : "—"}</strong>
            </div>
            <div>
              <span>Job</span>
              <strong className="mono small">{result.job_id.slice(0, 10)}</strong>
            </div>
          </div>

          {meta ? (
            <>
              <div className="divider" />
              <div className="mini-heading">Selected layer</div>
              <div className="legend-gradient">
                {meta.legend.map((stop) => (
                  <span key={stop.value} style={{ background: stop.color }} title={`${stop.label} ${meta.units}`} />
                ))}
              </div>
              <div className="legend-scale">
                <span>{formatNumber(meta.vmin, 3)} {meta.units}</span>
                <span>{meta.legend_title}</span>
                <span>{formatNumber(meta.vmax, 3)} {meta.units}</span>
              </div>
              <p className="fine-print">{meta.method}. {meta.source}.</p>
            </>
          ) : null}

          {layers.data?.limitations.length ? (
            <>
              <div className="divider" />
              <div className="mini-heading">Limitations</div>
              <ul className="tight-list">
                {layers.data.limitations.map((item, index) => (
                  <li key={index}>{item}</li>
                ))}
              </ul>
            </>
          ) : null}

          <div className="divider" />
          <div className="report-actions">
            <button className="btn btn-sm btn-ghost" onClick={() => void generateReport("html")} disabled={reportBusy !== null}>
              {reportBusy === "html" ? "Generating…" : "HTML report"}
            </button>
            {report ? (
              <a className="btn btn-sm btn-primary" href={reportDownloadUrl(report.id)} target="_blank" rel="noreferrer">
                Download
              </a>
            ) : null}
          </div>
        </aside>
      </div>

      <div className="detail-grid-two">
        <section className="panel">
          <div className="panel-head">
            <div>
              <div className="kicker">Measurements</div>
              <h2>Statistics</h2>
            </div>
            <span className="muted">units: {result.units || "mixed"}</span>
          </div>
          <div className="stat-list">
            {statisticEntries.map(([key, value]) => (
              <div className="stat-row" key={key}>
                <span>{titleCase(key)}</span>
                <strong>
                  <StatValue value={value} units={unitForKey(key)} />
                </strong>
              </div>
            ))}
          </div>
          {result.statistics.limitations ? (
            <div className="guardrail-note">
              <strong>Scientific limitations:</strong>{" "}
              {Array.isArray(result.statistics.limitations)
                ? result.statistics.limitations.join(" ")
                : String(result.statistics.limitations)}
            </div>
          ) : null}
        </section>

        <section className="panel">
          <div className="panel-head">
            <div>
              <div className="kicker">Reproducibility</div>
              <h2>Processing provenance</h2>
            </div>
            <span className="status status-good">immutable</span>
          </div>
          {result.run ? (
            <>
              <div className="run-head">
                <div>
                  <span>Algorithm</span>
                  <strong>{result.run.algorithm}</strong>
                </div>
                <div>
                  <span>Version</span>
                  <strong>v{result.run.algorithm_version}</strong>
                </div>
                <div>
                  <span>Code version</span>
                  <strong className="mono small">{result.run.code_version}</strong>
                </div>
                <div>
                  <span>CRS</span>
                  <strong>{result.run.crs}</strong>
                </div>
              </div>
              <div className="divider" />
              <div className="mini-heading">Input products ({result.run.input_product_ids.length})</div>
              <div className="id-list">
                {result.run.input_product_ids.map((id) => (
                  <code key={id}>{id}</code>
                ))}
              </div>
              <div className="divider" />
              <details className="json-details" open>
                <summary>Run parameters</summary>
                <pre className="json-block small">{JSON.stringify(result.run.parameters, null, 2)}</pre>
              </details>
              <details className="json-details">
                <summary>Full provenance record</summary>
                <pre className="json-block small">{JSON.stringify(result.run.provenance, null, 2)}</pre>
              </details>
              <p className="fine-print">
                Execution {formatDate(result.run.started_at, true)}
                {result.run.finished_at ? ` → ${formatDate(result.run.finished_at, true)}` : ""}.
              </p>
            </>
          ) : (
            <p className="muted">No processing run is linked to this result.</p>
          )}
        </section>
      </div>

      <section className="panel">
        <div className="panel-head">
          <div>
            <div className="kicker">Model evidence</div>
            <h2>SARVEX-HFCE classification</h2>
          </div>
          <span className="muted">{hfce.data?.available ? "available" : "unavailable"}</span>
        </div>
        {hfce.loading ? <LoadingBlock label="Running HFCE" rows={3} /> : null}
        {hfce.error ? <ErrorState error={hfce.error} retry={hfce.reload} /> : null}
        {hfce.data?.available && hfce.data.prediction ? (
          <>
            <div className="stat-grid stat-grid-compact">
              <div>
                <span>Predicted type</span>
                <strong>{hfce.data.prediction.event_type.replaceAll("_", " ")}</strong>
              </div>
              <div>
                <span>Change probability</span>
                <strong>{formatPercent(hfce.data.prediction.change_probability)}</strong>
              </div>
              <div>
                <span>Confidence</span>
                <strong>{formatPercent(hfce.data.prediction.confidence)}</strong>
              </div>
              <div>
                <span>Uncertainty</span>
                <strong>{formatNumber(hfce.data.prediction.uncertainty, 3)}</strong>
              </div>
              <div>
                <span>Baseline score</span>
                <strong>{formatNumber(hfce.data.prediction.baseline_score, 3)}</strong>
              </div>
              <div>
                <span>ML score</span>
                <strong>{formatNumber(hfce.data.prediction.ml_score, 3)}</strong>
              </div>
            </div>
            {hfce.data.prediction.top_features.length ? (
              <div className="stat-list" style={{ marginTop: 12 }}>
                <div className="mini-heading">Top contributing features</div>
                {hfce.data.prediction.top_features.map((item, index) => (
                  <div className="stat-row" key={index}>
                    <span>{item.feature}</span>
                    <strong>
                      {typeof item.importance === "number"
                        ? item.importance.toFixed(4)
                        : item.value !== undefined
                          ? String(item.value)
                          : "—"}
                    </strong>
                  </div>
                ))}
              </div>
            ) : null}
            {hfce.data.caveat ? <p className="fine-print">{hfce.data.caveat}</p> : null}
          </>
        ) : (
          <p className="muted">HFCE model is not available for this result.</p>
        )}
      </section>

      {timeseries.data?.length ? (
        <section className="panel">
          <div className="panel-head">
            <div>
              <div className="kicker">Temporal signal</div>
              <h2>Time series</h2>
            </div>
            <span className="muted">{timeseries.data.length} series</span>
          </div>
          <div className="timeseries-grid">
            {timeseries.data.map((series) => (
              <div className="series-card" key={series.id}>
                <div className="series-head">
                  <div>
                    <strong>{titleCase(series.series_type)}</strong>
                    <span>{series.unit} · {series.points.length} epochs</span>
                  </div>
                  <span className="mono small">{formatNumber(series.confidence, 2)} conf.</span>
                </div>
                <Sparkline series={series} />
                <div className="series-trend">
                  {Object.entries(series.trend)
                    .filter(([, value]) => typeof value === "number" || typeof value === "string")
                    .slice(0, 4)
                    .map(([key, value]) => (
                      <span key={key}>
                        <em>{titleCase(key)}</em>
                        <strong>{typeof value === "number" ? formatNumber(value, 4) : String(value)}</strong>
                      </span>
                    ))}
                </div>
                {series.change_points.length ? (
                  <p className="fine-print">
                    {series.change_points.length} change point(s) recorded; markers show indices, not causality.
                  </p>
                ) : null}
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <div className="detail-grid-two">
        <section className="panel">
          <div className="panel-head">
            <div>
              <div className="kicker">Vector products</div>
              <h2>Detected features</h2>
            </div>
            <span className="muted">{features.data?.length ?? 0} features</span>
          </div>
          {features.error ? (
            <ErrorState error={features.error} retry={features.reload} />
          ) : features.loading ? (
            <LoadingBlock label="Loading features" rows={4} />
          ) : features.data?.length ? (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Type</th>
                    <th>Value</th>
                    <th>Area</th>
                    <th>Confidence</th>
                    <th>Uncertainty</th>
                  </tr>
                </thead>
                <tbody>
                  {features.data.map((feature) => (
                    <tr key={feature.id}>
                      <td>{titleCase(feature.feature_type)}</td>
                      <td>{formatNumber(feature.value, 3)} {feature.unit || ""}</td>
                      <td>{formatArea(typeof feature.properties.area_m2 === "number" ? feature.properties.area_m2 : null)}</td>
                      <td>{feature.confidence !== null ? formatPercent(feature.confidence) : "—"}</td>
                      <td>{formatNumber(feature.uncertainty, 3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="muted">No vector features were persisted for this result.</p>
          )}
        </section>

        <section className="panel">
          <div className="panel-head">
            <div>
              <div className="kicker">Detected change</div>
              <h2>Events</h2>
            </div>
            <Link className="text-link" to="/events">Review queue →</Link>
          </div>
          {result.events.length ? (
            <div className="event-mini-list">
              {result.events.map((event) => (
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
                    <span>{event.magnitude !== null ? `${formatNumber(event.magnitude, 2)} ${event.magnitude_unit || ""}` : "—"}</span>
                    <span>{formatNumber(event.confidence, 2)} conf.</span>
                  </div>
                </Link>
              ))}
            </div>
          ) : (
            <p className="muted">No events crossed the configured detection threshold.</p>
          )}
        </section>
      </div>

      <section className="panel copilot-section">
        <CopilotPanel resultId={result.id} />
      </section>
    </div>
  );
}
