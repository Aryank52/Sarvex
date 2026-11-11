import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { buildQuery, patch, post } from "../api/client";
import { ApiError } from "../api/client";
import type {
  ContextLayer,
  EventDetail,
  EventFeatureCollection,
  EventStats,
  EventSummary,
  Evidence,
  Exposure,
  Page,
} from "../api/types";
import { useApi } from "../hooks/useApi";
import {
  formatArea,
  formatDate,
  formatNumber,
  formatPercent,
  titleCase,
} from "../lib/format";
import { MapView } from "../components/MapView";
import {
  DemoTag,
  ErrorState,
  LoadingBlock,
  SectionHeader,
  StageBadge,
  StatusBadge,
} from "../components/States";

const TRANSITIONS: Record<string, string[]> = {
  UNREVIEWED: ["UNDER_REVIEW", "REJECTED", "ARCHIVED"],
  UNDER_REVIEW: ["CORROBORATED", "REJECTED", "ARCHIVED", "UNREVIEWED"],
  CORROBORATED: ["ARCHIVED", "UNDER_REVIEW"],
  REJECTED: ["UNDER_REVIEW", "ARCHIVED"],
  ARCHIVED: ["UNDER_REVIEW"],
};

const SOURCE_TYPES = [
  "OFFICIAL_REPORT",
  "SEISMIC_CATALOGUE",
  "HYDROLOGICAL_GAUGE",
  "FIELD_VALIDATION",
  "PEER_REVIEWED_STUDY",
  "OPERATIONAL_RECORD",
];

export function Events() {
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedEventId = searchParams.get("event");
  const [stage, setStage] = useState("");
  const [status, setStatus] = useState("");
  const [eventType, setEventType] = useState("");
  const [rationale, setRationale] = useState("");
  const [nextStatus, setNextStatus] = useState("");
  const [externalUrl, setExternalUrl] = useState("");
  const [actionBusy, setActionBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [confirmSuccess, setConfirmSuccess] = useState<string | null>(null);
  const [confirmForm, setConfirmForm] = useState({
    evidence_title: "",
    source_type: "OFFICIAL_REPORT",
    url: "",
    citation: "",
    publisher: "",
    rationale: "",
  });

  const filterQuery = buildQuery({
    limit: 100,
    taxonomy_stage: stage,
    status,
    event_type: eventType,
  });
  const events = useApi<Page<EventSummary>>(`/events${filterQuery}`);
  const geojson = useApi<EventFeatureCollection>(`/events/geojson${filterQuery}`);
  const stats = useApi<EventStats>("/events/stats");
  const detail = useApi<EventDetail>(selectedEventId ? `/events/${selectedEventId}` : null);
  const evidence = useApi<Evidence[]>(selectedEventId ? `/events/${selectedEventId}/evidence` : null);
  const context = useApi<ContextLayer[]>(selectedEventId ? `/events/${selectedEventId}/context` : null);
  const exposures = useApi<Exposure[]>(selectedEventId ? `/events/${selectedEventId}/exposures` : null);

  const eventTypes = useMemo(() => {
    const values = new Set<string>();
    events.data?.items.forEach((event) => values.add(event.event_type));
    return [...values].sort();
  }, [events.data]);

  function selectEvent(id: string) {
    const next = new URLSearchParams(searchParams);
    next.set("event", id);
    setSearchParams(next, { replace: true });
    setRationale("");
    setNextStatus("");
    setExternalUrl("");
    setActionError(null);
    setConfirmError(null);
    setConfirmSuccess(null);
    setConfirmForm({
      evidence_title: "",
      source_type: "OFFICIAL_REPORT",
      url: "",
      citation: "",
      publisher: "",
      rationale: "",
    });
  }

  function refreshSelection() {
    detail.reload();
    evidence.reload();
    context.reload();
    exposures.reload();
    events.reload();
    geojson.reload();
    stats.reload();
  }

  async function updateStatus(event: React.FormEvent) {
    event.preventDefault();
    if (!selectedEventId || !nextStatus) return;
    setActionBusy(true);
    setActionError(null);
    try {
      await patch(`/events/${selectedEventId}/status`, {
        status: nextStatus,
        rationale: rationale || undefined,
        external_evidence_url: externalUrl || undefined,
      });
      setRationale("");
      setNextStatus("");
      setExternalUrl("");
      refreshSelection();
    } catch (error) {
      setActionError(error instanceof ApiError ? error.message : "Status update failed.");
    } finally {
      setActionBusy(false);
    }
  }

  async function confirmEvent(event: React.FormEvent) {
    event.preventDefault();
    if (!selectedEventId) return;
    setConfirmBusy(true);
    setConfirmError(null);
    setConfirmSuccess(null);
    try {
      const response = await post<{ message: string; taxonomy_stage: string; evidence_id: string }>(
        `/events/${selectedEventId}/confirm`,
        {
          evidence_title: confirmForm.evidence_title,
          source_type: confirmForm.source_type,
          url: confirmForm.url || undefined,
          citation: confirmForm.citation || undefined,
          publisher: confirmForm.publisher || undefined,
          rationale: confirmForm.rationale,
        },
      );
      setConfirmSuccess(`${response.message} Evidence ${response.evidence_id.slice(0, 8)}… linked.`);
      refreshSelection();
    } catch (error) {
      setConfirmError(
        error instanceof ApiError
          ? `${error.message}${error.correlationId ? ` (ref ${error.correlationId.slice(0, 10)})` : ""}`
          : "Confirmation failed.",
      );
    } finally {
      setConfirmBusy(false);
    }
  }

  const selected = detail.data;
  const allowed = selected ? TRANSITIONS[selected.status] || [] : [];

  return (
    <div className="page-stack">
      <SectionHeader
        kicker="Change event review"
        title="Separate detection from confirmation"
        description="Detection is algorithmic. Confirmation requires authoritative, independent evidence — and synthetic demo events can never be confirmed."
        actions={
          <span className="data-mode-chip">
            {stats.data ? `${stats.data.total} events · ${stats.data.demo} demo` : "loading stats"}
          </span>
        }
      />

      <div className="stage-summary">
        {["DETECTED", "CLASSIFIED", "HYPOTHESIZED", "CONTEXTUALIZED", "CONFIRMED"].map((item) => (
          <button
            key={item}
            className={`stage-summary-item${stage === item ? " active" : ""}`}
            onClick={() => setStage(stage === item ? "" : item)}
          >
            <StageBadge stage={item} />
            <strong>{stats.data?.by_taxonomy_stage[item] ?? 0}</strong>
            <span>{item === "DETECTED" ? "algorithmic" : item === "CONFIRMED" ? "independently evidenced" : "staged claim"}</span>
          </button>
        ))}
      </div>

      <div className="explore-toolbar">
        <div className="filter-group">
          <label htmlFor="event-stage">Taxonomy stage</label>
          <select id="event-stage" value={stage} onChange={(event) => setStage(event.target.value)}>
            <option value="">All stages</option>
            <option value="DETECTED">Detected</option>
            <option value="CLASSIFIED">Classified</option>
            <option value="HYPOTHESIZED">Hypothesized</option>
            <option value="CONTEXTUALIZED">Contextualized</option>
            <option value="CONFIRMED">Confirmed</option>
          </select>
        </div>
        <div className="filter-group">
          <label htmlFor="event-status">Review status</label>
          <select id="event-status" value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="">All statuses</option>
            {["UNREVIEWED", "UNDER_REVIEW", "CORROBORATED", "REJECTED", "ARCHIVED"].map((item) => (
              <option key={item} value={item}>{titleCase(item)}</option>
            ))}
          </select>
        </div>
        <div className="filter-group">
          <label htmlFor="event-type">Event type</label>
          <select id="event-type" value={eventType} onChange={(event) => setEventType(event.target.value)}>
            <option value="">All types</option>
            {eventTypes.map((item) => (
              <option key={item} value={item}>{titleCase(item)}</option>
            ))}
          </select>
        </div>
        <div className="toolbar-spacer" />
        <span className="muted">{events.data?.total ?? 0} matching events</span>
      </div>

      <div className="events-layout">
        <div className="events-left">
          <section className="panel map-panel">
            {geojson.error ? (
              <ErrorState error={geojson.error} retry={geojson.reload} />
            ) : geojson.data ? (
              <MapView
                events={geojson.data}
                selectedEventId={selectedEventId}
                onSelectEvent={selectEvent}
                height={400}
                interactive
              />
            ) : (
              <LoadingBlock label="Loading event map" rows={5} />
            )}
            <div className="map-caption">
              <span>Click an event to inspect it. Colour denotes evidence stage.</span>
              <span>{geojson.data?.metadata.notice || "No synthetic geometry in this filtered view"}</span>
            </div>
          </section>

          <section className="panel">
            <div className="panel-head">
              <div>
                <div className="kicker">Filtered registry</div>
                <h2>Change events</h2>
              </div>
            </div>
            {events.error ? (
              <ErrorState error={events.error} retry={events.reload} />
            ) : events.loading ? (
              <LoadingBlock label="Loading events" />
            ) : events.data?.items.length ? (
              <div className="event-list">
                {events.data.items.map((event) => (
                  <button
                    key={event.id}
                    className={`event-list-row${selectedEventId === event.id ? " active" : ""}`}
                    onClick={() => selectEvent(event.id)}
                  >
                    <div className="event-list-main">
                      <div className="event-list-top">
                        <StageBadge stage={event.taxonomy_stage} />
                        <StatusBadge status={event.status} />
                        {event.is_demo ? <DemoTag /> : null}
                        <span className="mono small">{event.id.slice(0, 8)}</span>
                      </div>
                      <strong>{titleCase(event.event_type)}</strong>
                      <p>{event.summary}</p>
                      <div className="event-mini-meta">
                        <span>{formatArea(event.area_m2)}</span>
                        <span>{formatDate(event.start_time)}</span>
                        <span>{formatPercent(event.confidence)} confidence</span>
                      </div>
                    </div>
                    <span className="chevron">›</span>
                  </button>
                ))}
              </div>
            ) : (
              <p className="muted">No events match the current filters.</p>
            )}
          </section>
        </div>

        <aside className="events-side">
          {selected ? (
            <>
              <section className="panel detail-card">
                <div className="detail-top">
                  <StageBadge stage={selected.taxonomy_stage} />
                  <StatusBadge status={selected.status} />
                  {selected.is_demo ? <DemoTag /> : null}
                </div>
                <div className="kicker">{selected.event_type.replaceAll("_", " ")}</div>
                <h2>Event detail</h2>
                <p className="detail-summary">{selected.summary}</p>

                <div className="stat-grid stat-grid-compact">
                  <div><span>Area</span><strong>{formatArea(selected.area_m2)}</strong></div>
                  <div>
                    <span>Magnitude</span>
                    <strong>{selected.magnitude !== null ? `${formatNumber(selected.magnitude, 2)} ${selected.magnitude_unit || ""}` : "—"}</strong>
                  </div>
                  <div><span>Confidence</span><strong>{formatPercent(selected.confidence)}</strong></div>
                  <div><span>Uncertainty</span><strong>{formatNumber(selected.uncertainty, 3)}</strong></div>
                  <div><span>Severity</span><strong>{formatNumber(selected.severity, 3)}</strong></div>
                  <div><span>Priority</span><strong>{selected.priority ?? "—"}</strong></div>
                  <div><span>Detected start</span><strong>{formatDate(selected.start_time, true)}</strong></div>
                  <div><span>Detected end</span><strong>{formatDate(selected.end_time, true)}</strong></div>
                </div>

                <div className="divider" />
                <div className="mini-heading">Method and provenance</div>
                <div className="kv-list">
                  <div><span>Classification method</span><strong>{selected.classification_method || "—"}</strong></div>
                  <div><span>Classification confidence</span><strong>{formatPercent(selected.classification_confidence)}</strong></div>
                  <div><span>Run</span><strong className="mono small">{selected.run_id ? selected.run_id.slice(0, 12) : "—"}</strong></div>
                  <div><span>Observations</span><strong>{selected.observation_ids.length}</strong></div>
                </div>
                <p className="fine-print">
                  Taxonomy stage expresses evidence strength, not hazard probability. A DETECTED event
                  may be spatially real but its cause remains undetermined.
                </p>
              </section>

              <section className="panel detail-card">
                <div className="mini-heading">Review workflow</div>
                {selected.is_demo ? (
                  <div className="gate-note">
                    <strong>Demo event</strong>
                    <p>
                      Derived from synthetic fixtures. Status review is allowed, but confirmation is
                      blocked by the API because synthetic data cannot establish a real-world event.
                    </p>
                  </div>
                ) : null}
                <form className="review-form" onSubmit={updateStatus}>
                  <div className="field">
                    <label htmlFor="next-status">Next status</label>
                    <select id="next-status" value={nextStatus} onChange={(event) => setNextStatus(event.target.value)}>
                      <option value="">Choose an allowed transition…</option>
                      {allowed.map((item) => (
                        <option key={item} value={item}>{titleCase(item)}</option>
                      ))}
                    </select>
                  </div>
                  {nextStatus === "CORROBORATED" ? (
                    <div className="field">
                      <label htmlFor="external-url">External evidence URL</label>
                      <input
                        id="external-url"
                        value={externalUrl}
                        onChange={(event) => setExternalUrl(event.target.value)}
                        placeholder="https://authoritative-source…"
                      />
                      <small className="field-help">
                        Corroboration requires a URL. Full confirmation uses the evidence gate below.
                      </small>
                    </div>
                  ) : null}
                  <div className="field">
                    <label htmlFor="review-rationale">Review rationale</label>
                    <textarea
                      id="review-rationale"
                      rows={3}
                      value={rationale}
                      onChange={(event) => setRationale(event.target.value)}
                      placeholder="Record why the status is changing. This is audited."
                    />
                  </div>
                  {actionError ? <div className="inline-error">{actionError}</div> : null}
                  <button className="btn btn-primary" type="submit" disabled={!nextStatus || actionBusy}>
                    {actionBusy ? "Updating…" : "Update status"}
                  </button>
                </form>

                <div className="divider" />
                <div className="mini-heading">Independent confirmation</div>
                {selected.is_demo ? (
                  <div className="gate-note gate-blocked">
                    <strong>Confirmation disabled</strong>
                    <p>Synthetic demo events can never be promoted to CONFIRMED.</p>
                  </div>
                ) : selected.taxonomy_stage === "CONFIRMED" ? (
                  <div className="gate-note gate-ok">
                    <strong>Confirmed</strong>
                    <p>This event carries independently supplied evidence. Review the evidence below.</p>
                  </div>
                ) : (
                  <form className="confirm-form" onSubmit={confirmEvent}>
                    <div className="field">
                      <label htmlFor="evidence-title">Evidence title</label>
                      <input
                        id="evidence-title"
                        required
                        minLength={3}
                        value={confirmForm.evidence_title}
                        onChange={(event) => setConfirmForm((current) => ({ ...current, evidence_title: event.target.value }))}
                        placeholder="Official flood bulletin 2026-08-11"
                      />
                    </div>
                    <div className="field">
                      <label htmlFor="evidence-type">Source type</label>
                      <select
                        id="evidence-type"
                        value={confirmForm.source_type}
                        onChange={(event) => setConfirmForm((current) => ({ ...current, source_type: event.target.value }))}
                      >
                        {SOURCE_TYPES.map((type) => (
                          <option key={type} value={type}>{titleCase(type)}</option>
                        ))}
                      </select>
                    </div>
                    <div className="field">
                      <label htmlFor="evidence-url">URL or full citation (at least one)</label>
                      <input
                        id="evidence-url"
                        value={confirmForm.url}
                        onChange={(event) => setConfirmForm((current) => ({ ...current, url: event.target.value }))}
                        placeholder="https://… or leave blank and supply a citation"
                      />
                      <input
                        className="stacked-input"
                        value={confirmForm.citation}
                        onChange={(event) => setConfirmForm((current) => ({ ...current, citation: event.target.value }))}
                        placeholder="Full citation if no URL"
                      />
                    </div>
                    <div className="field">
                      <label htmlFor="evidence-publisher">Publisher / authority</label>
                      <input
                        id="evidence-publisher"
                        value={confirmForm.publisher}
                        onChange={(event) => setConfirmForm((current) => ({ ...current, publisher: event.target.value }))}
                        placeholder="Example District Authority"
                      />
                    </div>
                    <div className="field">
                      <label htmlFor="evidence-rationale">Why does this evidence confirm the event?</label>
                      <textarea
                        id="evidence-rationale"
                        required
                        minLength={20}
                        rows={3}
                        value={confirmForm.rationale}
                        onChange={(event) => setConfirmForm((current) => ({ ...current, rationale: event.target.value }))}
                        placeholder="The independent source documents the same footprint and time window."
                      />
                    </div>
                    {confirmError ? <div className="inline-error">{confirmError}</div> : null}
                    {confirmSuccess ? <div className="inline-notice notice-ok">{confirmSuccess}</div> : null}
                    <button className="btn btn-primary" type="submit" disabled={confirmBusy}>
                      {confirmBusy ? "Validating evidence…" : "Confirm with independent evidence"}
                    </button>
                  </form>
                )}
              </section>

              <section className="panel detail-card">
                <div className="mini-heading">Evidence ({evidence.data?.length ?? 0})</div>
                {evidence.data?.length ? (
                  evidence.data.map((item) => (
                    <div className="linked-evidence" key={item.id}>
                      <strong>{item.title}</strong>
                      <span>{titleCase(item.source_type)} · {item.is_demo ? "demo" : "independent"}</span>
                      {item.snippet ? <p>{item.snippet}</p> : null}
                      {item.url ? <a href={item.url} target="_blank" rel="noreferrer">Open source ↗</a> : null}
                    </div>
                  ))
                ) : (
                  <p className="muted">
                    No independent evidence has been attached. The event remains at its recorded
                    evidence stage.
                  </p>
                )}
              </section>

              <section className="panel detail-card">
                <div className="mini-heading">Context and exposure</div>
                {context.data?.length ? (
                  <div className="context-list">
                    {context.data.map((item) => (
                      <div key={item.id}>
                        <strong>{item.name}</strong>
                        <span>{item.provider} · {item.license}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="muted">No context layers are linked.</p>
                )}
                {exposures.data?.length ? (
                  <div className="exposure-table">
                    {exposures.data.map((item) => (
                      <div key={item.id}>
                        <span>{item.asset?.name || item.asset_id}</span>
                        <strong>{formatPercent(item.exposure_score)}</strong>
                        <em>{formatNumber(item.distance_m, 0)} m</em>
                      </div>
                    ))}
                  </div>
                ) : null}
                <p className="fine-print">
                  Exposure is spatial proximity context only. It does not confirm damage, causation or
                  an operational impact.
                </p>
              </section>
            </>
          ) : (
            <section className="panel detail-card">
              <div className="kicker">Select an event</div>
              <h2>Review the evidence</h2>
              <p className="detail-summary">
                Choose an event from the map or registry to inspect its measurements, evidence stage,
                review history and independent evidence.
              </p>
              <div className="guardrail-note">
                <strong>Confirmation gate:</strong> only an external authoritative source can promote a
                real detection to CONFIRMED. Demo fixtures are permanently excluded.
              </div>
            </section>
          )}
        </aside>
      </div>
    </div>
  );
}
