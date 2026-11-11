import { useState } from "react";
import { ApiError, post } from "../api/client";
import type { ModelInfo, ModelSummary } from "../api/types";
import { useApi } from "../hooks/useApi";
import { formatDate, formatNumber, titleCase } from "../lib/format";
import {
  ErrorState,
  Kpi,
  LoadingBlock,
  SectionHeader,
  StatusBadge,
} from "../components/States";

type ModelsResponse = {
  models: ModelInfo[];
  summary: ModelSummary;
  config_path: string;
  principle: string;
};

type ModelRun = {
  id: string;
  purpose: string;
  model_name: string;
  model_version: string;
  status: string;
  latency_ms: number | null;
  error: string | null;
  correlation_id: string | null;
  created_at: string;
};

export function Models() {
  const models = useApi<ModelsResponse>("/models");
  const health = useApi<{ models: ModelInfo[]; summary: ModelSummary; config_path: string }>("/health/models");
  const runs = useApi<{ runs: ModelRun[] }>("/models/runs?limit=50");
  const hfce = useApi<{
    available: boolean;
    artifact_dir?: string;
    model_version?: string;
    metrics?: { validation: Record<string, number>; test: Record<string, number> };
    caveat?: string;
    trained_at?: string;
    n_samples?: number;
    class_distribution?: Record<string, number>;
    feature_importance?: Record<string, number>;
    shap_summary?: Record<string, number>;
  }>("/models/hfce/status");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function reload() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const response = await post<{ reloaded: boolean; synced_models: number }>("/models/reload");
      setNotice(`Registry reloaded · ${response.synced_models} model records synchronised to the database.`);
      models.reload();
      health.reload();
      runs.reload();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Model registry reload failed.");
    } finally {
      setBusy(false);
    }
  }

  const categories = (models.data?.models || []).reduce<Record<string, ModelInfo[]>>((groups, model) => {
    (groups[model.category] ||= []).push(model);
    return groups;
  }, {});

  return (
    <div className="page-stack">
      <SectionHeader
        kicker="Model registry"
        title="Configuration, not hard-coded models"
        description="Every embedding, reranker and language model is resolved from a declarative registry. Business logic asks for a capability, never a vendor name."
        actions={
          <>
            <a className="btn btn-ghost" href="/api/v1/models" target="_blank" rel="noreferrer">
              Registry JSON ↗
            </a>
            <button className="btn btn-primary" onClick={() => void reload()} disabled={busy}>
              {busy ? "Reloading…" : "Reload registry"}
            </button>
          </>
        }
      />

      {notice ? <div className="inline-notice notice-ok">{notice}</div> : null}
      {error ? <div className="inline-notice notice-error">{error}</div> : null}

      {models.data ? (
        <div className="kpi-grid kpi-grid-five">
          <Kpi
            label="Embedding"
            value={String(models.data.summary.embedding?.dimension ?? "—")}
            detail={String(models.data.summary.embedding?.name ?? "not configured")}
            tone="cyan"
          />
          <Kpi
            label="Vector storage"
            value={String(models.data.summary.storage_capacity ?? "—")}
            detail="pgvector capacity · zero-padded, never truncated"
            tone="violet"
          />
          <Kpi
            label="Language model"
            value={String(models.data.summary.llm?.provider ?? "—")}
            detail={String(models.data.summary.llm?.name ?? "not configured")}
            tone="amber"
          />
          <Kpi
            label="Reranker"
            value={String(models.data.summary.reranker?.provider ?? "—")}
            detail={String(models.data.summary.reranker?.name ?? "not configured")}
            tone="green"
          />
          <Kpi
            label="Configured models"
            value={models.data.models.length}
            detail={models.data.config_path.split(/[\\/]/).pop() || "models.yaml"}
            tone="cyan"
          />
        </div>
      ) : null}

      {models.error ? <ErrorState error={models.error} retry={models.reload} /> : null}
      {health.error ? <ErrorState error={health.error} retry={health.reload} /> : null}
      {models.loading ? <LoadingBlock label="Loading model registry" rows={5} /> : null}

      <section className="panel">
        <div className="panel-head">
          <div>
            <div className="kicker">Declared providers</div>
            <h2>Model catalog</h2>
          </div>
          <span className="muted">{models.data?.config_path}</span>
        </div>
        {Object.entries(categories).map(([category, entries]) => (
          <div className="model-group" key={category}>
            <div className="model-group-head">
              <h3>{titleCase(category)}</h3>
              <span>{entries.length} model{entries.length > 1 ? "s" : ""}</span>
            </div>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Model</th>
                    <th>Provider</th>
                    <th>Version</th>
                    <th>Task</th>
                    <th>Status</th>
                    <th>Default</th>
                    <th>Capabilities</th>
                  </tr>
                </thead>
                <tbody>
                  {entries.map((model) => (
                    <tr key={`${model.category}-${model.name}`}>
                      <td><span className="mono small">{model.name}</span></td>
                      <td>{model.provider}</td>
                      <td>{model.version}</td>
                      <td>{model.task || "—"}</td>
                      <td><StatusBadge status={model.status} /></td>
                      <td>{model.is_default ? "yes" : "—"}</td>
                      <td>
                        <code className="inline-json">
                          {Object.entries(model.capabilities)
                            .filter(([, value]) => ["string", "number", "boolean"].includes(typeof value))
                            .map(([key, value]) => `${key}=${String(value)}`)
                            .join(" · ") || "—"}
                        </code>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ))}
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <div className="kicker">SARVEX-HFCE</div>
            <h2>Trained model status</h2>
          </div>
          <span className="muted">{hfce.data?.available ? `v${hfce.data.model_version}` : "unavailable"}</span>
        </div>
        {hfce.error ? <ErrorState error={hfce.error} retry={hfce.reload} /> : null}
        {hfce.loading ? <LoadingBlock label="Loading HFCE status" rows={4} /> : null}
        {hfce.data?.available ? (
          <>
            <div className="kpi-grid kpi-grid-five">
              <Kpi label="Samples" value={hfce.data.n_samples ?? "—"} detail="pseudo-labelled (PSEUDO)" tone="cyan" />
              <Kpi label="Test accuracy" value={hfce.data.metrics?.test?.accuracy !== undefined ? `${(hfce.data.metrics.test.accuracy * 100).toFixed(1)}%` : "—"} detail="held-out split" tone="green" />
              <Kpi label="Test macro-F1" value={hfce.data.metrics?.test?.f1_macro !== undefined ? hfce.data.metrics.test.f1_macro.toFixed(3) : "—"} detail="held-out split" tone="violet" />
              <Kpi label="Test precision" value={hfce.data.metrics?.test?.precision_macro !== undefined ? hfce.data.metrics.test.precision_macro.toFixed(3) : "—"} detail="macro" tone="amber" />
              <Kpi label="Test recall" value={hfce.data.metrics?.test?.recall_macro !== undefined ? hfce.data.metrics.test.recall_macro.toFixed(3) : "—"} detail="macro" tone="cyan" />
            </div>
            <div className="guardrail-note">
              <strong>Caveat:</strong> {hfce.data.caveat} Trained {hfce.data.trained_at}.
            </div>
            {hfce.data.feature_importance ? (
              <div className="stat-list" style={{ marginTop: 12 }}>
                <div className="mini-heading">Feature importance (top)</div>
                {Object.entries(hfce.data.feature_importance)
                  .sort((a, b) => b[1] - a[1])
                  .slice(0, 8)
                  .map(([name, value]) => (
                    <div className="stat-row" key={name}>
                      <span>{name}</span>
                      <strong>{value.toFixed(4)}</strong>
                    </div>
                  ))}
              </div>
            ) : null}
          </>
        ) : (
          <p className="muted">HFCE model is not available. Run training to enable classification.</p>
        )}
      </section>

      <div className="detail-grid-two">
        <section className="panel">
          <div className="panel-head">
            <div>
              <div className="kicker">Invocations</div>
              <h2>Recent model runs</h2>
            </div>
            <span className="muted">{runs.data?.runs.length ?? 0} runs</span>
          </div>
          {runs.error ? (
            <ErrorState error={runs.error} retry={runs.reload} />
          ) : runs.loading ? (
            <LoadingBlock label="Loading model runs" rows={4} />
          ) : runs.data?.runs.length ? (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Purpose</th>
                    <th>Model</th>
                    <th>Status</th>
                    <th>Latency</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.data.runs.map((run) => (
                    <tr key={run.id}>
                      <td>{titleCase(run.purpose)}</td>
                      <td><span className="mono small">{run.model_name}</span></td>
                      <td><StatusBadge status={run.status} /></td>
                      <td>{run.latency_ms !== null ? `${formatNumber(run.latency_ms, 0)} ms` : "—"}</td>
                      <td>{formatDate(run.created_at, true)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="muted">No model invocations have been recorded yet.</p>
          )}
        </section>

        <section className="panel">
          <div className="panel-head">
            <div>
              <div className="kicker">Policy</div>
              <h2>Provider guarantees</h2>
            </div>
          </div>
          <ul className="rule-list">
            <li>
              <strong>Offline-safe defaults.</strong> Feature-hashing embeddings, lexical reranking and
              a deterministic grounded composer work without network access. They are marked
              semantically limited, not silently upgraded.
            </li>
            <li>
              <strong>No silent truncation.</strong> Vectors above the configured storage capacity are
              rejected; shorter vectors are zero-padded without changing cosine similarity.
            </li>
            <li>
              <strong>Degraded is visible.</strong> Provider health and degradation are exposed in
              responses, the health endpoint and the UI.
            </li>
            <li>
              <strong>Models never confirm.</strong> A model can explain detections. Only independent
              evidence can promote an event to CONFIRMED.
            </li>
          </ul>
          <div className="guardrail-note">
            <strong>Configuration path:</strong>{" "}
            <code>{models.data?.config_path || "backend/config/models.yaml"}</code>
          </div>
        </section>
      </div>
    </div>
  );
}
