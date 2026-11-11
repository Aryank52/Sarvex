import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { buildQuery, layerPngUrl } from "../api/client";
import type {
  EventDetail,
  EventFeatureCollection,
  Evidence,
  LayersResponse,
  Page,
  ResultSummary,
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
import {
  Confidence,
  DemoTag,
  ErrorState,
  LoadingBlock,
  SectionHeader,
  StageBadge,
  StatusBadge,
} from "../components/States";

const LAYER_PRIORITY = ["difference", "displacement", "ratio_change", "deformation_mask", "before", "after", "vv"];

function pickLayer(layers: LayersResponse): string | null {
  if (!layers.layers.length) return null;
  for (const preferred of LAYER_PRIORITY) {
    const found = layers.layers.find((layer) => layer.name === preferred);
    if (found) return found.name;
  }
  return layers.layers[0].name;
}

export function Explore() {
  const [stage, setStage] = useState("");
  const [eventType, setEventType] = useState("");
  const [status, setStatus] = useState("");
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [selectedResultId, setSelectedResultId] = useState<string | null>(null);
  const [selectedLayerName, setSelectedLayerName] = useState<string | null>(null);
  const [overlay, setOverlay] = useState(true);

  const events = useApi<EventFeatureCollection>(
    `/events/geojson${buildQuery({ limit: 800, taxonomy_stage: stage, event_type: eventType, status })}`,
  );
  const results = useApi<Page<ResultSummary>>("/results?limit=100");
  const layers = useApi<LayersResponse>(selectedResultId ? `/results/${selectedResultId}/layers` : null);
  const eventDetail = useApi<EventDetail>(selectedEventId ? `/events/${selectedEventId}` : null);
  const eventEvidence = useApi<Evidence[]>(selectedEventId ? `/events/${selectedEventId}/evidence` : null);

  useEffect(() => {
    if (!results.data || selectedResultId) return;
    const first = results.data.items[0];
    if (first) setSelectedResultId(first.id);
  }, [results.data, selectedResultId]);

  useEffect(() => {
    if (!layers.data) return;
    const available = layers.data.layers.map((layer) => layer.name);
    if (!selectedLayerName || !available.includes(selectedLayerName)) {
      setSelectedLayerName(pickLayer(layers.data));
    }
  }, [layers.data, selectedLayerName]);

  const eventTypes = useMemo(() => {
    const values = new Set<string>();
    events.data?.features.forEach((feature) => {
      const value = feature.properties.event_type;
      if (value) values.add(String(value));
    });
    return [...values].sort();
  }, [events.data]);

  const selectedResult = results.data?.items.find((item) => item.id === selectedResultId) || null;
  const activeMeta = layers.data?.layers.find((layer) => layer.name === selectedLayerName) || null;

  const mapLayer: MapLayer | null = useMemo(() => {
    if (!overlay || !selectedResult || !activeMeta) return null;
    return {
      url: layerPngUrl(selectedResult.id, activeMeta.name),
      coordinates: activeMeta.image_coordinates,
      name: activeMeta.name,
    };
  }, [overlay, selectedResult, activeMeta]);

  const selectedEvent = eventDetail.data || null;

  return (
    <div className="page-stack">
      <SectionHeader
        kicker="Spatial explorer"
        title="Explore measured change"
        description="Overlay processing layers on labelled event geometry. Every colour is tied to a unit, a range and a method — never a decorative heatmap."
        actions={
          <Link className="btn btn-ghost" to="/analyses">
            Run a new analysis
          </Link>
        }
      />

      <div className="explore-toolbar">
        <div className="filter-group">
          <label htmlFor="explore-stage">Evidence stage</label>
          <select id="explore-stage" value={stage} onChange={(event) => setStage(event.target.value)}>
            <option value="">All stages</option>
            <option value="DETECTED">Detected</option>
            <option value="CLASSIFIED">Classified</option>
            <option value="HYPOTHESIZED">Hypothesized</option>
            <option value="CONFIRMED">Confirmed</option>
          </select>
        </div>
        <div className="filter-group">
          <label htmlFor="explore-type">Event type</label>
          <select id="explore-type" value={eventType} onChange={(event) => setEventType(event.target.value)}>
            <option value="">All types</option>
            {eventTypes.map((type) => (
              <option key={type} value={type}>
                {titleCase(type)}
              </option>
            ))}
          </select>
        </div>
        <div className="filter-group">
          <label htmlFor="explore-status">Review status</label>
          <select id="explore-status" value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="">All statuses</option>
            <option value="UNREVIEWED">Unreviewed</option>
            <option value="UNDER_REVIEW">Under review</option>
            <option value="CORROBORATED">Corroborated</option>
            <option value="REJECTED">Rejected</option>
            <option value="ARCHIVED">Archived</option>
          </select>
        </div>
        <div className="toolbar-spacer" />
        <div className="filter-group filter-grow">
          <label htmlFor="explore-result">Result layer</label>
          <select
            id="explore-result"
            value={selectedResultId || ""}
            onChange={(event) => {
              setSelectedResultId(event.target.value || null);
              setSelectedLayerName(null);
            }}
          >
            <option value="">No result overlay</option>
            {results.data?.items.map((result) => (
              <option key={result.id} value={result.id}>
                {titleCase(result.result_type)} · {formatDate(result.created_at)}
              </option>
            ))}
          </select>
        </div>
        <div className="filter-group">
          <label htmlFor="explore-layer">Layer</label>
          <select
            id="explore-layer"
            value={selectedLayerName || ""}
            onChange={(event) => setSelectedLayerName(event.target.value || null)}
            disabled={!layers.data?.layers.length}
          >
            {layers.data?.layers.map((layer) => (
              <option key={layer.name} value={layer.name}>
                {layer.title}
              </option>
            ))}
          </select>
        </div>
        <label className="switch">
          <input type="checkbox" checked={overlay} onChange={(event) => setOverlay(event.target.checked)} />
          <span>Overlay</span>
        </label>
      </div>

      <div className="explore-grid">
        <section className="panel map-panel">
          <div className="map-topline">
            <span>
              {events.data?.metadata.count ?? 0} event geometries
              {mapLayer ? ` · ${activeMeta?.title}` : " · no raster overlay"}
            </span>
            <span>{events.data?.metadata.notice || "Click a polygon to inspect measured evidence"}</span>
          </div>
          {events.error ? (
            <ErrorState error={events.error} retry={events.reload} />
          ) : events.data ? (
            <MapView
              events={events.data}
              layer={mapLayer}
              selectedEventId={selectedEventId}
              onSelectEvent={(id) => setSelectedEventId(id)}
              height="min(64vh, 660px)"
            />
          ) : (
            <LoadingBlock label="Loading event layer" rows={5} />
          )}

          <div className="layer-strip">
            {layers.loading ? <span className="muted">Loading layers…</span> : null}
            {layers.data?.layers.map((layer) => (
              <button
                key={layer.name}
                className={`layer-chip${selectedLayerName === layer.name ? " active" : ""}`}
                onClick={() => {
                  setSelectedLayerName(layer.name);
                  setOverlay(true);
                }}
              >
                <span className="ramp" style={{ background: `linear-gradient(90deg, ${layer.legend.map((stop) => stop.color).join(",")})` }} />
                <span>
                  <strong>{layer.title}</strong>
                  <small>
                    {layer.units} · {layer.method}
                  </small>
                </span>
              </button>
            )) || null}
          </div>
        </section>

        <aside className="explore-side">
          {selectedEvent ? (
            <section className="panel detail-card">
              <div className="detail-top">
                <StageBadge stage={selectedEvent.taxonomy_stage} />
                <StatusBadge status={selectedEvent.status} />
                {selectedEvent.is_demo ? <DemoTag /> : null}
              </div>
              <div className="kicker">{titleCase(selectedEvent.event_type)}</div>
              <h2>Measured event</h2>
              <p className="detail-summary">{selectedEvent.summary}</p>

              <div className="stat-grid stat-grid-compact">
                <div>
                  <span>Area</span>
                  <strong>{formatArea(selectedEvent.area_m2)}</strong>
                </div>
                <div>
                  <span>Magnitude</span>
                  <strong>
                    {selectedEvent.magnitude !== null
                      ? `${formatNumber(selectedEvent.magnitude, 2)} ${selectedEvent.magnitude_unit || ""}`
                      : "—"}
                  </strong>
                </div>
                <div>
                  <span>Confidence</span>
                  <strong>{selectedEvent.confidence !== null ? formatPercent(selectedEvent.confidence) : "—"}</strong>
                </div>
                <div>
                  <span>Uncertainty</span>
                  <strong>{formatNumber(selectedEvent.uncertainty, 3)}</strong>
                </div>
                <div>
                  <span>Detected</span>
                  <strong>{formatDate(selectedEvent.start_time)}</strong>
                </div>
                <div>
                  <span>Method</span>
                  <strong className="truncate">{selectedEvent.classification_method || "—"}</strong>
                </div>
              </div>

              <div className="divider" />
              <div className="mini-heading">Linked evidence</div>
              {eventEvidence.loading ? <span className="muted">Loading evidence…</span> : null}
              {eventEvidence.data?.length ? (
                eventEvidence.data.map((item) => (
                  <div className="linked-evidence" key={item.id}>
                    <strong>{item.title}</strong>
                    <span>{titleCase(item.source_type)}</span>
                    {item.url ? (
                      <a href={item.url} target="_blank" rel="noreferrer">
                        Open source ↗
                      </a>
                    ) : null}
                  </div>
                ))
              ) : (
                <p className="muted">No independent evidence is attached. The event remains staged as recorded.</p>
              )}

              {selectedEvent.exposures.length ? (
                <>
                  <div className="divider" />
                  <div className="mini-heading">Exposure context</div>
                  {selectedEvent.exposures.slice(0, 3).map((exposure) => (
                    <div className="exposure-row" key={exposure.id}>
                      <span>{exposure.asset?.name || exposure.asset_id}</span>
                      <strong>{formatPercent(exposure.exposure_score)}</strong>
                    </div>
                  ))}
                  <p className="fine-print">
                    Exposure is proximity-based context. It is not damage confirmation or a causal
                    claim.
                  </p>
                </>
              ) : null}

              <div className="detail-actions">
                <Link className="btn btn-primary btn-sm" to={`/events?event=${selectedEvent.id}`}>
                  Review in Events
                </Link>
                <button className="btn btn-ghost btn-sm" onClick={() => setSelectedEventId(null)}>
                  Clear selection
                </button>
              </div>
            </section>
          ) : activeMeta && selectedResult ? (
            <section className="panel detail-card">
              <div className="detail-top">
                <span className="layer-kind">RASTER LAYER</span>
                {layers.data?.is_demo ? <DemoTag /> : null}
              </div>
              <div className="kicker">{selectedResult.result_type.replaceAll("_", " ")}</div>
              <h2>{activeMeta.title}</h2>
              <p className="detail-summary">
                {activeMeta.method}. Rendered from a georeferenced GeoTIFF; the PNG overlay uses the
                documented image coordinates. Units: <strong>{activeMeta.units}</strong>.
              </p>

              <div className="legend-block">
                <div className="legend-gradient">
                  {activeMeta.legend.map((stop) => (
                    <span key={stop.value} style={{ background: stop.color }} title={`${stop.label} ${activeMeta.units}`} />
                  ))}
                </div>
                <div className="legend-scale">
                  <span>
                    {formatNumber(activeMeta.vmin, 3)} {activeMeta.units}
                  </span>
                  <span>{activeMeta.legend_title}</span>
                  <span>
                    {formatNumber(activeMeta.vmax, 3)} {activeMeta.units}
                  </span>
                </div>
              </div>

              <div className="stat-grid stat-grid-compact">
                <div>
                  <span>Valid pixels</span>
                  <strong>{formatPercent(activeMeta.valid_fraction)}</strong>
                </div>
                <div>
                  <span>Raster size</span>
                  <strong>
                    {activeMeta.width} × {activeMeta.height}
                  </strong>
                </div>
                <div>
                  <span>CRS</span>
                  <strong>{activeMeta.crs || "—"}</strong>
                </div>
                <div>
                  <span>Products</span>
                  <strong>{activeMeta.product_ids.length}</strong>
                </div>
                <div>
                  <span>Source</span>
                  <strong className="truncate">{activeMeta.source}</strong>
                </div>
                <div>
                  <span>Result confidence</span>
                  <strong>{selectedResult.confidence !== null ? formatPercent(selectedResult.confidence) : "—"}</strong>
                </div>
              </div>

              <div className="coord-readout">
                <span>Overlay corners (WGS84)</span>
                <code>{activeMeta.image_coordinates.map((coordinate) => `[${coordinate[0].toFixed(3)}, ${coordinate[1].toFixed(3)}]`).join(" ")}</code>
              </div>

              {layers.data?.limitations.length ? (
                <details className="limitations" open>
                  <summary>Layer limitations</summary>
                  <ul>
                    {layers.data.limitations.map((item, index) => (
                      <li key={index}>{item}</li>
                    ))}
                  </ul>
                </details>
              ) : null}

              <div className="detail-actions">
                <Link className="btn btn-primary btn-sm" to={`/analyses/${selectedResult.id}`}>
                  Open analysis
                </Link>
                <a
                  className="btn btn-ghost btn-sm"
                  href={layerPngUrl(selectedResult.id, activeMeta.name)}
                  target="_blank"
                  rel="noreferrer"
                >
                  Raw PNG ↗
                </a>
              </div>
            </section>
          ) : (
            <section className="panel detail-card">
              <div className="kicker">Selection</div>
              <h2>Inspect the evidence</h2>
              <p className="detail-summary">
                Click an event polygon to see its stage, uncertainty and independent evidence. Pick a
                result and layer above to overlay measured SAR products on the map.
              </p>
              <div className="stat-grid stat-grid-compact">
                <div>
                  <span>Rendered events</span>
                  <strong>{events.data?.metadata.count ?? 0}</strong>
                </div>
                <div>
                  <span>Analyses available</span>
                  <strong>{results.data?.total ?? 0}</strong>
                </div>
                <div>
                  <span>Demo mode</span>
                  <strong>{events.data?.metadata.demo_mode ? "ON" : "OFF"}</strong>
                </div>
                <div>
                  <span>Data mode</span>
                  <strong>{events.data?.metadata.demo_mode ? "synthetic" : "mixed"}</strong>
                </div>
              </div>
              <div className="guardrail-note">
                Event polygons are algorithmic detections. Category labels do not assert a cause,
                and a detection is never automatically promoted to confirmation.
              </div>
            </section>
          )}

          <section className="panel detail-card">
            <div className="mini-heading">Evidence legend</div>
            <div className="stage-key">
              {[
                ["DETECTED", "Algorithmic change region"],
                ["CLASSIFIED", "Rule/model label"],
                ["HYPOTHESIZED", "Unverified explanation"],
                ["CONFIRMED", "Independent evidence"],
              ].map(([label, copy]) => (
                <div key={label}>
                  <StageBadge stage={label} />
                  <span>{copy}</span>
                </div>
              ))}
            </div>
          </section>
        </aside>
      </div>

      <section className="panel">
        <div className="panel-head">
          <div>
            <div className="kicker">Result inventory</div>
            <h2>Available measured layers</h2>
          </div>
          <span className="muted">{results.data?.total ?? 0} results</span>
        </div>
        {results.error ? <ErrorState error={results.error} retry={results.reload} /> : null}
        {results.loading ? <LoadingBlock label="Loading analyses" /> : null}
        {results.data?.items.length ? (
          <div className="result-cards">
            {results.data.items.map((result) => (
              <button
                key={result.id}
                className={`result-card${selectedResultId === result.id ? " active" : ""}`}
                onClick={() => {
                  setSelectedResultId(result.id);
                  setSelectedLayerName(null);
                }}
              >
                <div className="result-card-top">
                  <span>{titleCase(result.result_type)}</span>
                  {result.is_demo ? <DemoTag /> : null}
                </div>
                <p>{result.summary}</p>
                <div className="result-card-meta">
                  <span>{result.units || "unitless"}</span>
                  <span>{formatDate(result.created_at)}</span>
                  <Confidence value={result.confidence} />
                </div>
              </button>
            ))}
          </div>
        ) : (
          <p className="muted">No results are available. Run an analysis to populate the explorer.</p>
        )}
      </section>

      <div className="metric-inline">
        {[
          ["Selected stage", stage ? titleCase(stage) : "All stages"],
          ["Selected type", eventType ? titleCase(eventType) : "All types"],
          ["Selected status", status ? titleCase(status) : "All statuses"],
          ["Confidence semantics", "Detection confidence ≠ hazard probability"],
        ].map(([label, value]) => (
          <div key={label}>
            <span>{label}</span>
            <strong>{value}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}
