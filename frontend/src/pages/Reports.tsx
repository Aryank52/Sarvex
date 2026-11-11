import { useEffect, useState } from "react";
import { ApiError, post, reportDownloadUrl, request } from "../api/client";
import type {
  EventSummary,
  Page,
  Report,
  ReportSummary,
  ResultSummary,
} from "../api/types";
import { useApi } from "../hooks/useApi";
import { formatDate, titleCase } from "../lib/format";
import {
  DemoTag,
  ErrorState,
  LoadingBlock,
  SectionHeader,
  StatusBadge,
} from "../components/States";

export function Reports() {
  const reports = useApi<Page<ReportSummary>>("/reports?limit=100");
  const results = useApi<Page<ResultSummary>>("/results?limit=100");
  const events = useApi<Page<EventSummary>>("/events?limit=100");

  const [target, setTarget] = useState<"result" | "event">("result");
  const [resultId, setResultId] = useState("");
  const [eventId, setEventId] = useState("");
  const [format, setFormat] = useState<"markdown" | "html">("markdown");
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [preview, setPreview] = useState<Report | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  useEffect(() => {
    if (!resultId && results.data?.items.length) setResultId(results.data.items[0].id);
  }, [results.data, resultId]);
  useEffect(() => {
    if (!eventId && events.data?.items.length) setEventId(events.data.items[0].id);
  }, [events.data, eventId]);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      const report = await post<Report>("/reports", {
        result_id: target === "result" ? resultId : undefined,
        event_id: target === "event" ? eventId : undefined,
        format,
        title: title || undefined,
      });
      setMessage({ kind: "ok", text: `Report ${report.id.slice(0, 8)}… generated with provenance attached.` });
      setPreview(report);
      reports.reload();
      setTitle("");
    } catch (error) {
      setMessage({
        kind: "error",
        text:
          error instanceof ApiError
            ? `${error.message}${error.correlationId ? ` (ref ${error.correlationId.slice(0, 10)})` : ""}`
            : "Report generation failed.",
      });
    } finally {
      setBusy(false);
    }
  }

  async function openReport(id: string) {
    setPreviewLoading(true);
    try {
      const report = await request<Report>(`/reports/${id}`);
      setPreview(report);
    } catch (error) {
      setMessage({
        kind: "error",
        text: error instanceof ApiError ? error.message : "Could not load report.",
      });
    } finally {
      setPreviewLoading(false);
    }
  }

  return (
    <div className="page-stack">
      <SectionHeader
        kicker="Reports"
        title="Reproducible evidence bundles"
        description="Reports carry input products, methods, statistics, evidence stages, model runs, attribution and limitations. Demo fixtures remain labelled in the document."
        actions={<span className="data-mode-chip">{reports.data ? `${reports.data.total} reports` : "loading"}</span>}
      />

      {message ? (
        <div className={`inline-notice ${message.kind === "error" ? "notice-error" : "notice-ok"}`}>
          {message.text}
          <button onClick={() => setMessage(null)} aria-label="Dismiss">×</button>
        </div>
      ) : null}

      <div className="reports-grid">
        <form className="panel" onSubmit={create}>
          <div className="panel-head">
            <div>
              <div className="kicker">New document</div>
              <h2>Generate a report</h2>
            </div>
          </div>
          <div className="field">
            <label>Report subject</label>
            <div className="segmented">
              <button type="button" className={target === "result" ? "active" : ""} onClick={() => setTarget("result")}>
                Analysis result
              </button>
              <button type="button" className={target === "event" ? "active" : ""} onClick={() => setTarget("event")}>
                Change event
              </button>
            </div>
          </div>
          {target === "result" ? (
            <div className="field">
              <label htmlFor="report-result">Analysis result</label>
              <select id="report-result" value={resultId} onChange={(event) => setResultId(event.target.value)}>
                {results.data?.items.map((result) => (
                  <option key={result.id} value={result.id}>
                    {titleCase(result.result_type)} · {formatDate(result.created_at)} · {result.units || "unitless"}
                  </option>
                ))}
              </select>
            </div>
          ) : (
            <div className="field">
              <label htmlFor="report-event">Change event</label>
              <select id="report-event" value={eventId} onChange={(event) => setEventId(event.target.value)}>
                {events.data?.items.map((event) => (
                  <option key={event.id} value={event.id}>
                    {titleCase(event.event_type)} · {event.taxonomy_stage} · {formatDate(event.start_time)}
                  </option>
                ))}
              </select>
            </div>
          )}
          <div className="field">
            <label htmlFor="report-title">Title override (optional)</label>
            <input
              id="report-title"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Use the generated scientific title"
            />
          </div>
          <div className="field">
            <label>Format</label>
            <div className="segmented">
              <button type="button" className={format === "markdown" ? "active" : ""} onClick={() => setFormat("markdown")}>
                Markdown
              </button>
              <button type="button" className={format === "html" ? "active" : ""} onClick={() => setFormat("html")}>
                HTML
              </button>
            </div>
          </div>
          <button className="btn btn-primary" type="submit" disabled={busy || (target === "result" ? !resultId : !eventId)}>
            {busy ? "Assembling evidence…" : "Generate report"}
          </button>
          <p className="fine-print">
            Generated documents are immutable snapshots. They cite the result or event by ID and
            include demo-mode notices when applicable.
          </p>
        </form>

        <section className="panel">
          <div className="panel-head">
            <div>
              <div className="kicker">Library</div>
              <h2>Generated reports</h2>
            </div>
            {reports.loading ? <span className="muted">Loading…</span> : null}
          </div>
          {reports.error ? (
            <ErrorState error={reports.error} retry={reports.reload} />
          ) : reports.loading ? (
            <LoadingBlock label="Loading reports" rows={4} />
          ) : reports.data?.items.length ? (
            <div className="report-list">
              {reports.data.items.map((report) => (
                <div className="report-row" key={report.id}>
                  <div className="report-main">
                    <div className="report-title">
                      <strong>{report.title}</strong>
                      <span className="mode-pill">{report.format.toUpperCase()}</span>
                      <span className="mono small">{report.id.slice(0, 8)}</span>
                    </div>
                    <div className="report-meta">
                      <span>{titleCase(report.report_type)}</span>
                      <span>{formatDate(report.created_at, true)}</span>
                      {report.result_id ? <span>result {report.result_id.slice(0, 8)}</span> : null}
                      {report.event_id ? <span>event {report.event_id.slice(0, 8)}</span> : null}
                    </div>
                  </div>
                  <div className="report-actions">
                    <button className="btn btn-sm btn-ghost" onClick={() => void openReport(report.id)}>
                      Preview
                    </button>
                    <a className="btn btn-sm btn-primary" href={reportDownloadUrl(report.id)} target="_blank" rel="noreferrer">
                      Download
                    </a>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="muted">No reports yet. Generate one from a measured result or a change event.</p>
          )}
        </section>
      </div>

      <section className="panel">
        <div className="mini-heading">What every report contains</div>
        <div className="report-sections">
          {[
            ["Data sources", "Products, providers, acquisition dates, bands, polarization and attribution."],
            ["Method", "Algorithm, version, parameters, CRS, units and full provenance JSON."],
            ["Measurements", "Statistics with units and uncertainty; no invented values."],
            ["Detected events", "Stage, confidence, method and magnitude, never asserted causes."],
            ["Model and copilot runs", "Configured models, latency and validation state."],
            ["Limitations", "Relative measurements, threshold choices, spatial proximity caveats."],
          ].map(([title, copy]) => (
            <div key={title}>
              <strong>{title}</strong>
              <p>{copy}</p>
            </div>
          ))}
        </div>
      </section>

      {preview ? (
        <div className="modal-backdrop" onClick={() => setPreview(null)}>
          <div className="modal modal-wide" onClick={(event) => event.stopPropagation()}>
            <div className="modal-head">
              <div>
                <div className="kicker">{preview.format} report</div>
                <h2>{preview.title}</h2>
              </div>
              <div className="modal-actions">
                <a className="btn btn-sm btn-primary" href={reportDownloadUrl(preview.id)} target="_blank" rel="noreferrer">
                  Download
                </a>
                <button className="icon-btn" onClick={() => setPreview(null)} aria-label="Close preview">×</button>
              </div>
            </div>
            <div className="preview-meta">
              <StatusBadge status="COMPLETED" />
              <span>{formatDate(preview.created_at, true)}</span>
              {preview.provenance.demo ? <DemoTag /> : null}
              <span className="mono small">{preview.id}</span>
            </div>
            {preview.format === "html" ? (
              <iframe className="report-frame" title={preview.title} srcDoc={preview.content} sandbox="" />
            ) : (
              <pre className="report-pre">{preview.content}</pre>
            )}
          </div>
        </div>
      ) : null}

      {previewLoading ? (
        <div className="modal-backdrop">
          <div className="modal">
            <LoadingBlock label="Loading report preview" rows={8} />
          </div>
        </div>
      ) : null}
    </div>
  );
}
