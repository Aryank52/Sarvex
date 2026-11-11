import type { ReactNode } from "react";
import type { ApiError } from "../api/client";
import { stageClass, statusClass, titleCase } from "../lib/format";

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="spinner-wrap" role="status" aria-live="polite">
      <span className="spinner" />
      <span>{label}…</span>
    </div>
  );
}

export function LoadingBlock({ label = "Loading", rows = 3 }: { label?: string; rows?: number }) {
  return (
    <div className="skeleton-card" aria-busy="true">
      <div className="skeleton skeleton-title" />
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className={`skeleton skeleton-line${index % 2 ? " short" : ""}`} />
      ))}
      <span className="sr-only">{label}</span>
    </div>
  );
}

export function ErrorState({ error, retry }: { error: ApiError; retry?: () => void }) {
  return (
    <div className="error-card" role="alert">
      <div className="error-icon">!</div>
      <div>
        <h3>{error.status === 0 ? "API unavailable" : "Request failed"}</h3>
        <p>{error.message}</p>
        <div className="error-meta">
          <span>{error.code}</span>
          {error.status ? <span>HTTP {error.status}</span> : null}
          {error.correlationId ? <span>ref {error.correlationId.slice(0, 12)}</span> : null}
        </div>
        {error.detail ? (
          <details className="error-detail">
            <summary>Technical detail</summary>
            <pre>{JSON.stringify(error.detail, null, 2)}</pre>
          </details>
        ) : null}
        {retry ? (
          <button className="btn btn-ghost btn-sm" onClick={retry}>
            Retry
          </button>
        ) : null}
      </div>
    </div>
  );
}

export function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-glyph" aria-hidden="true">
        ◌
      </div>
      <h3>{title}</h3>
      {children ? <p>{children}</p> : null}
      {action}
    </div>
  );
}

const STAGE_COPY: Record<string, string> = {
  OBSERVED: "Instrument values as measured.",
  DERIVED: "A quantity computed from observations.",
  DETECTED: "A region flagged by a stated algorithm.",
  CLASSIFIED: "A rule or model label; confirmation is still pending.",
  HYPOTHESIZED: "A proposed explanation that requires independent validation.",
  CONTEXTUALIZED: "Related external context; proximity is not causality.",
  CONFIRMED: "Supported by independent, authoritative evidence.",
};

export function StageBadge({ stage }: { stage: string | null | undefined }) {
  const value = (stage || "OBSERVED").toUpperCase();
  return (
    <span className={stageClass(value)} title={STAGE_COPY[value] || "Evidence stage"}>
      {value}
    </span>
  );
}

export function StatusBadge({ status }: { status: string | null | undefined }) {
  return <span className={statusClass(status)}>{titleCase(status || "unknown")}</span>;
}

export function Confidence({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined) return <span className="muted">—</span>;
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <span className="confidence" title="Detection confidence, not hazard probability">
      <span className="confidence-track">
        <span className="confidence-fill" style={{ width: `${pct}%` }} />
      </span>
      <span className="confidence-value">{pct.toFixed(0)}%</span>
    </span>
  );
}

export function DemoTag() {
  return <span className="demo-mini">DEMO</span>;
}

export function SectionHeader({
  kicker,
  title,
  description,
  actions,
}: {
  kicker?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="section-header">
      <div>
        {kicker ? <div className="kicker">{kicker}</div> : null}
        <h1>{title}</h1>
        {description ? <p className="section-lead">{description}</p> : null}
      </div>
      {actions ? <div className="section-actions">{actions}</div> : null}
    </div>
  );
}

export function Kpi({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: ReactNode;
  detail?: string;
  tone?: "cyan" | "amber" | "violet" | "green";
}) {
  return (
    <div className={`kpi${tone ? ` kpi-${tone}` : ""}`}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {detail ? <div className="kpi-detail">{detail}</div> : null}
    </div>
  );
}

export function ProgressBar({ value, label }: { value: number; label?: string }) {
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div className="progress">
      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="progress-label">
        <span>{label || "Progress"}</span>
        <span>{pct.toFixed(0)}%</span>
      </div>
    </div>
  );
}
