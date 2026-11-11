import { useMemo, useState } from "react";
import type {
  CopilotSession,
  EventSummary,
  Page,
  ResultSummary,
} from "../api/types";
import { useApi } from "../hooks/useApi";
import { formatDate, titleCase } from "../lib/format";
import { CopilotPanel } from "../components/CopilotPanel";
import {
  DemoTag,
  ErrorState,
  LoadingBlock,
  SectionHeader,
  StageBadge,
} from "../components/States";

export function Copilot() {
  const results = useApi<Page<ResultSummary>>("/results?limit=100");
  const events = useApi<Page<EventSummary>>("/events?limit=100");
  const stats = useApi<{
    documents: number;
    chunks: number;
    embeddings: number;
    embedding_model: string;
    reranker_model: string;
    llm_model: string;
    demo_documents: number;
  }>("/knowledge/stats");
  const sessions = useApi<{ sessions: CopilotSession[] }>("/copilot/sessions?limit=20");

  const [contextKind, setContextKind] = useState<"result" | "event" | "none">("result");
  const [resultId, setResultId] = useState("");
  const [eventId, setEventId] = useState("");

  const contextKey = useMemo(
    () => `${contextKind}:${contextKind === "result" ? resultId : contextKind === "event" ? eventId : "none"}`,
    [contextKind, resultId, eventId],
  );

  return (
    <div className="page-stack">
      <SectionHeader
        kicker="AI copilot"
        title="Explain the evidence, not invent it"
        description="The copilot receives bounded, read-only context: measured statistics, staged events and retrieved knowledge passages. Every answer is citation-checked and limited to the evidence on hand."
        actions={<span className="data-mode-chip">{stats.data ? `${stats.data.documents} docs · ${stats.data.chunks} passages` : "loading corpus"}</span>}
      />

      <div className="copilot-page-grid">
        <section className="panel copilot-section">
          <div className="context-picker">
            <div className="field">
              <label>Grounding context</label>
              <div className="segmented">
                <button className={contextKind === "result" ? "active" : ""} onClick={() => setContextKind("result")}>
                  Analysis result
                </button>
                <button className={contextKind === "event" ? "active" : ""} onClick={() => setContextKind("event")}>
                  Change event
                </button>
                <button className={contextKind === "none" ? "active" : ""} onClick={() => setContextKind("none")}>
                  Knowledge only
                </button>
              </div>
            </div>
            {contextKind === "result" ? (
              <div className="field">
                <label htmlFor="copilot-result">Result</label>
                <select id="copilot-result" value={resultId} onChange={(event) => setResultId(event.target.value)}>
                  <option value="">Use the latest measured result</option>
                  {results.data?.items.map((result) => (
                    <option key={result.id} value={result.id}>
                      {titleCase(result.result_type)} · {formatDate(result.created_at)} · {result.units || "unitless"}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}
            {contextKind === "event" ? (
              <div className="field">
                <label htmlFor="copilot-event">Event</label>
                <select id="copilot-event" value={eventId} onChange={(event) => setEventId(event.target.value)}>
                  <option value="">Choose a change event…</option>
                  {events.data?.items.map((event) => (
                    <option key={event.id} value={event.id}>
                      {titleCase(event.event_type)} · {event.taxonomy_stage} · {formatDate(event.start_time)}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}
            <div className="context-note">
              {contextKind === "none"
                ? "No measured context will be sent. Answers can only cite the retrieved corpus and will say so."
                : "Measured context is attached read-only. The model cannot alter, recompute or confirm measurements."}
            </div>
          </div>

          <CopilotPanel
            key={contextKey}
            resultId={contextKind === "result" ? resultId || undefined : undefined}
            eventId={contextKind === "event" ? eventId || undefined : undefined}
          />
        </section>

        <aside className="copilot-side">
          <section className="panel">
            <div className="mini-heading">How grounding works</div>
            <ol className="step-list">
              <li>
                <strong>Retrieve.</strong> Hybrid lexical + vector search returns ranked passages with
                document, section and source priority.
              </li>
              <li>
                <strong>Assemble.</strong> Bounded tools add only structured measurements, stage and
                uncertainty.
              </li>
              <li>
                <strong>Compose.</strong> The configured language provider writes an explanation using
                the supplied evidence.
              </li>
              <li>
                <strong>Validate.</strong> Every [S#] citation must resolve. Causal language is
                neutralised before confirmation.
              </li>
            </ol>
            <div className="guardrail-note">
              No model name is hard-coded in application logic. The registry selects providers; the
              offline-safe default is deterministic and extractive.
            </div>
          </section>

          <section className="panel">
            <div className="mini-heading">Evidence stages in answers</div>
            <div className="stage-key">
              <div><StageBadge stage="OBSERVED" /><span>Measured or retrieved passage.</span></div>
              <div><StageBadge stage="DERIVED" /><span>Computed measurement with units.</span></div>
              <div><StageBadge stage="HYPOTHESIZED" /><span>Explanation requiring validation.</span></div>
              <div><StageBadge stage="CONFIRMED" /><span>Only with independent evidence.</span></div>
            </div>
            <p className="fine-print">
              Confidence is detection/answer confidence, never a hazard probability.
            </p>
          </section>

          <section className="panel">
            <div className="mini-heading">Corpus configuration</div>
            {stats.error ? <ErrorState error={stats.error} retry={stats.reload} /> : null}
            {stats.loading ? <LoadingBlock label="Loading corpus stats" rows={3} /> : null}
            {stats.data ? (
              <div className="kv-list">
                <div><span>Documents</span><strong>{stats.data.documents}</strong></div>
                <div><span>Chunks</span><strong>{stats.data.chunks}</strong></div>
                <div><span>Embeddings</span><strong>{stats.data.embeddings}</strong></div>
                <div><span>Embedding model</span><strong className="mono small">{stats.data.embedding_model}</strong></div>
                <div><span>Reranker</span><strong className="mono small">{stats.data.reranker_model}</strong></div>
                <div><span>LLM</span><strong className="mono small">{stats.data.llm_model}</strong></div>
                <div><span>Demo documents</span><strong>{stats.data.demo_documents}</strong></div>
              </div>
            ) : null}
          </section>

          <section className="panel">
            <div className="panel-head compact-head">
              <div className="mini-heading">Recent sessions</div>
              <span className="muted">{sessions.data?.sessions.length ?? 0}</span>
            </div>
            {sessions.error ? <ErrorState error={sessions.error} retry={sessions.reload} /> : null}
            {sessions.loading ? <LoadingBlock label="Loading sessions" rows={2} /> : null}
            {sessions.data?.sessions.length ? (
              <div className="session-list">
                {sessions.data.sessions.map((session) => (
                  <div key={session.id} className="session-row">
                    <strong>{session.title}</strong>
                    <span>
                      {session.messages} messages · {formatDate(session.updated_at, true)}
                    </span>
                    <span className="mono small">{session.id.slice(0, 12)}</span>
                    {session.result_id ? <DemoTag /> : null}
                  </div>
                ))}
              </div>
            ) : (
              <p className="muted">No copilot sessions yet.</p>
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}
