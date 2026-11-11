import { useMemo, useRef, useState } from "react";
import { ApiError, post } from "../api/client";
import type { CopilotResponse } from "../api/types";
import { titleCase } from "../lib/format";
import { DemoTag, StageBadge } from "./States";

type Turn = {
  id: string;
  question: string;
  response?: CopilotResponse;
  error?: string;
};

function AnswerText({ text }: { text: string }) {
  const parts = text.split(/(\[S\d+\])/g);
  return (
    <p className="copilot-answer">
      {parts.map((part, index) =>
        /^\[S\d+\]$/.test(part) ? (
          <mark key={index} className="citation-marker">
            {part}
          </mark>
        ) : (
          <span key={index}>{part}</span>
        ),
      )}
    </p>
  );
}

function EvidenceCard({ item }: { item: CopilotResponse["evidence"][number] }) {
  return (
    <article className="evidence-card">
      <div className="evidence-head">
        <span className="citation-id">{item.citation_id}</span>
        <strong>{item.title}</strong>
        {item.is_demo ? <DemoTag /> : null}
      </div>
      <p>{item.snippet}</p>
      <div className="evidence-foot">
        <span>{item.publisher || "Publisher not recorded"}</span>
        {item.url ? (
          <a href={item.url} target="_blank" rel="noreferrer">
            Open source ↗
          </a>
        ) : (
          <span className="muted">No external URL</span>
        )}
      </div>
    </article>
  );
}

function FindingsGroup({ label, items, tone }: { label: string; items: string[]; tone: string }) {
  if (!items.length) return null;
  return (
    <div className={`finding-group finding-${tone}`}>
      <div className="finding-label">{label}</div>
      <ul>
        {items.map((item, index) => (
          <li key={index}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

export function CopilotPanel({
  resultId,
  eventId,
  aoiId,
  compact = false,
  seedQuestion,
}: {
  resultId?: string;
  eventId?: string;
  aoiId?: string;
  compact?: boolean;
  seedQuestion?: string;
}) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [fatal, setFatal] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  const prompts = useMemo(() => {
    if (resultId) {
      return [
        "Summarize the measured change, its units and uncertainty.",
        "Which evidence stage applies, and what would confirmation require?",
        "What are the scientific limitations of this result?",
      ];
    }
    if (eventId) {
      return [
        "What did SARVEX measure in this event?",
        "Why is this not a confirmed hazard?",
        "Which external evidence could corroborate it?",
      ];
    }
    return [
      "Explain the difference between DETECTED and CONFIRMED in SARVEX.",
      "How does SAR backscatter change relate to surface properties?",
      "What uncertainties apply to InSAR displacement?",
    ];
  }, [resultId, eventId]);

  async function ask(text: string) {
    const clean = text.trim();
    if (!clean || busy) return;
    const turnId = `${Date.now()}-${turns.length}`;
    setTurns((current) => [...current, { id: turnId, question: clean }]);
    setQuestion("");
    setBusy(true);
    setFatal(null);
    try {
      const response = await post<CopilotResponse>("/copilot/ask", {
        question: clean,
        session_id: sessionId || undefined,
        result_id: resultId || undefined,
        event_id: eventId || undefined,
        aoi_id: aoiId || undefined,
        top_k: 6,
      });
      setSessionId(response.session_id);
      setTurns((current) =>
        current.map((turn) => (turn.id === turnId ? { ...turn, response } : turn)),
      );
    } catch (error) {
      const message =
        error instanceof ApiError ? `${error.message}${error.correlationId ? ` (ref ${error.correlationId.slice(0, 10)})` : ""}` : "Copilot request failed.";
      setTurns((current) =>
        current.map((turn) => (turn.id === turnId ? { ...turn, error: message } : turn)),
      );
      setFatal(message);
    } finally {
      setBusy(false);
      window.setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }), 50);
    }
  }

  return (
    <div className={`copilot${compact ? " copilot-compact" : ""}`}>
      {!compact ? (
        <div className="copilot-head">
          <div>
            <div className="kicker">Evidence-grounded copilot</div>
            <h2>Ask the measurements</h2>
            <p>
              Read-only tools assemble measured context and retrieved sources. The model explains
              evidence; it never invents measurements or confirms an event.
            </p>
          </div>
          <div className="copilot-head-actions">
            {sessionId ? <span className="session-id">session {sessionId.slice(0, 8)}</span> : null}
            {turns.length ? (
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => {
                  setTurns([]);
                  setSessionId(null);
                  setFatal(null);
                }}
              >
                New session
              </button>
            ) : null}
          </div>
        </div>
      ) : null}

      {turns.length === 0 ? (
        <div className="copilot-starters">
          <div className="starter-label">Grounded starting points</div>
          <div className="starter-grid">
            {prompts.map((prompt) => (
              <button key={prompt} className="starter" onClick={() => void ask(prompt)}>
                <span>→</span>
                {prompt}
              </button>
            ))}
          </div>
          {seedQuestion ? (
            <button className="starter starter-seed" onClick={() => void ask(seedQuestion)}>
              <span>→</span>
              {seedQuestion}
            </button>
          ) : null}
        </div>
      ) : null}

      <div className="copilot-thread">
        {turns.map((turn) => (
          <div key={turn.id} className="copilot-turn">
            <div className="user-message">
              <span>YOU</span>
              <p>{turn.question}</p>
            </div>
            {turn.error ? (
              <div className="assistant-error">{turn.error}</div>
            ) : !turn.response ? (
              <div className="assistant-loading">
                <span className="spinner" /> Retrieving evidence and validating citations…
              </div>
            ) : (
              <div className="assistant-message">
                <div className="assistant-meta">
                  <StageBadge stage={turn.response.taxonomy_stage} />
                  <span className="confidence-text">confidence: {turn.response.confidence}</span>
                  <span className={turn.response.citations_validated ? "validated" : "invalid"}>
                    {turn.response.citations_validated ? "citations validated" : "citation check failed"}
                  </span>
                  {turn.response.demo_mode ? <DemoTag /> : null}
                  {turn.response.degraded ? <span className="degraded">degraded provider</span> : null}
                </div>
                <AnswerText text={turn.response.answer} />

                <div className="findings-grid">
                  <FindingsGroup label="OBSERVED" items={turn.response.observed_facts} tone="observed" />
                  <FindingsGroup label="DERIVED" items={turn.response.derived_findings} tone="derived" />
                  <FindingsGroup
                    label="INTERPRETATION / HYPOTHESIS"
                    items={turn.response.interpretations}
                    tone="hypothesis"
                  />
                  <FindingsGroup label="UNCERTAINTY" items={turn.response.uncertainties} tone="uncertainty" />
                </div>

                {turn.response.evidence.length ? (
                  <div className="evidence-list">
                    <div className="finding-label">Retrieved evidence</div>
                    {turn.response.evidence.map((item) => (
                      <EvidenceCard key={item.citation_id + item.title} item={item} />
                    ))}
                  </div>
                ) : null}

                {turn.response.limitations.length ? (
                  <details className="limitations">
                    <summary>Limitations ({turn.response.limitations.length})</summary>
                    <ul>
                      {turn.response.limitations.map((item, index) => (
                        <li key={index}>{item}</li>
                      ))}
                    </ul>
                  </details>
                ) : null}

                <div className="assistant-foot">
                  <span>
                    {turn.response.provider} / {turn.response.model} v{turn.response.model_version}
                  </span>
                  <span>{titleCase(String(turn.response.retrieval.reranker || "retrieval"))}</span>
                </div>
              </div>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {fatal ? <div className="inline-error">{fatal}</div> : null}

      <form
        className="copilot-composer"
        onSubmit={(event) => {
          event.preventDefault();
          void ask(question);
        }}
      >
        <textarea
          rows={compact ? 2 : 3}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Ask about measured change, evidence stages, uncertainty, or method…"
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void ask(question);
            }
          }}
        />
        <div className="composer-foot">
          <span>Read-only. No shell, filesystem, or network tools. Enter to send.</span>
          <button className="btn btn-primary" type="submit" disabled={busy || question.trim().length < 2}>
            {busy ? "Grounding…" : "Ask"}
          </button>
        </div>
      </form>
    </div>
  );
}
