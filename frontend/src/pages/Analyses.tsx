import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, post } from "../api/client";
import type {
  AOI,
  Capabilities,
  Job,
  JobCreateResponse,
  Page,
  Product,
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
import {
  DemoTag,
  ErrorState,
  LoadingBlock,
  ProgressBar,
  SectionHeader,
  StageBadge,
  StatusBadge,
} from "../components/States";

type ParamField = {
  key: string;
  label: string;
  placeholder: string;
  help: string;
};

const COMPATIBILITY: Record<string, string[]> = {
  backscatter: ["GCOV", "GSLC"],
  change_detection: ["GCOV", "GSLC"],
  deformation: ["GUNW", "RUNW"],
  polarimetric: ["GCOV"],
  offsets: ["RSLC", "GSLC", "GCOV"],
  timeseries: ["GCOV", "GSLC"],
};

const PARAMS: Record<string, ParamField[]> = {
  backscatter: [
    { key: "z_threshold", label: "MAD z threshold", placeholder: "3.5", help: "Robust deviation threshold." },
    { key: "min_change_db", label: "Minimum change (dB)", placeholder: "1.0", help: "Physical floor in decibels." },
    { key: "min_area_px", label: "Minimum area (pixels)", placeholder: "6", help: "Connected-component cleanup." },
  ],
  change_detection: [
    { key: "z_threshold", label: "MAD z threshold", placeholder: "3.5", help: "Robust deviation threshold." },
    { key: "min_change_db", label: "Minimum change (dB)", placeholder: "1.0", help: "Physical floor in decibels." },
    { key: "min_area_px", label: "Minimum area (pixels)", placeholder: "6", help: "Connected-component cleanup." },
  ],
  deformation: [
    { key: "coherence_threshold", label: "Coherence threshold", placeholder: "0.3", help: "Pixels below this are masked." },
    { key: "min_displacement_mm", label: "Minimum |LOS| (mm)", placeholder: "10", help: "Detection floor; no hazard inference." },
    { key: "min_area_px", label: "Minimum area (pixels)", placeholder: "4", help: "Connected-component cleanup." },
    { key: "looks", label: "Multilook factor", placeholder: "4", help: "Phase-variance scaling." },
  ],
  polarimetric: [
    { key: "ratio_change_threshold_db", label: "Ratio change threshold (dB)", placeholder: "1.5", help: "VV/VH ratio deviation." },
    { key: "min_area_px", label: "Minimum area (pixels)", placeholder: "6", help: "Connected-component cleanup." },
  ],
  offsets: [],
  timeseries: [],
};

const ACTIVE_STATES = new Set(["QUEUED", "CLAIMED", "VALIDATING", "DOWNLOADING", "PREPROCESSING", "PROCESSING", "ANALYZING", "POSTPROCESSING"]);

function makeParams(type: string, values: Record<string, string>): Record<string, unknown> {
  const fields = PARAMS[type] || [];
  const result: Record<string, unknown> = {};
  for (const field of fields) {
    const raw = values[field.key];
    if (raw === undefined || raw.trim() === "") continue;
    const numeric = Number(raw);
    result[field.key] = Number.isFinite(numeric) ? numeric : raw;
  }
  return result;
}

export function Analyses() {
  const products = useApi<Page<Product>>("/products?limit=300");
  const aois = useApi<Page<AOI>>("/aois?limit=100");
  const capabilities = useApi<Capabilities>("/capabilities");
  const jobs = useApi<Page<Job>>("/analyses?limit=100");
  const results = useApi<Page<ResultSummary>>("/results?limit=100");

  const [analysisType, setAnalysisType] = useState("backscatter");
  const [selectedProducts, setSelectedProducts] = useState<string[]>([]);
  const [selectedAoi, setSelectedAoi] = useState("");
  const [createAoi, setCreateAoi] = useState(false);
  const [aoiName, setAoiName] = useState("Custom analysis AOI");
  const [aoiBbox, setAoiBbox] = useState("91.55,26.05,91.95,26.32");
  const [parameters, setParameters] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [openLogs, setOpenLogs] = useState<string | null>(null);

  const compatibleTypes = useMemo(
    () => capabilities.data?.analysis_types.find((item) => item.type === analysisType)?.modes || COMPATIBILITY[analysisType] || [],
    [analysisType, capabilities.data],
  );
  const minProducts = capabilities.data?.analysis_types.find((item) => item.type === analysisType)?.min_products || 1;

  useEffect(() => {
    if (!selectedAoi && aois.data?.items.length) setSelectedAoi(aois.data.items[0].id);
  }, [aois.data, selectedAoi]);

  useEffect(() => {
    setSelectedProducts((current) =>
      current.filter((id) => {
        const product = products.data?.items.find((item) => item.id === id);
        return product ? compatibleTypes.includes(product.product_type) : false;
      }),
    );
    setParameters({});
  }, [analysisType, compatibleTypes, products.data]);

  useEffect(() => {
    if (!jobs.data?.items.some((job) => ACTIVE_STATES.has(job.status))) return;
    const timer = window.setInterval(() => jobs.reload(), 3500);
    return () => window.clearInterval(timer);
  }, [jobs.data?.items, jobs]);

  const compatibleProducts = products.data?.items.filter((product) => compatibleTypes.includes(product.product_type)) || [];
  const canRun = selectedProducts.length >= minProducts && (createAoi ? aoiBbox.split(",").length === 4 : Boolean(selectedAoi));

  function toggleProduct(productId: string) {
    setSelectedProducts((current) =>
      current.includes(productId) ? current.filter((id) => id !== productId) : [...current, productId],
    );
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      let aoiId = selectedAoi;
      if (createAoi) {
        const bounds = aoiBbox.split(",").map((value) => Number(value.trim()));
        if (bounds.length !== 4 || bounds.some((value) => !Number.isFinite(value))) {
          throw new ApiError("AOI bounds must be four comma-separated numbers.", 422, "validation_error");
        }
        const [minx, miny, maxx, maxy] = bounds;
        if (minx >= maxx || miny >= maxy) {
          throw new ApiError("AOI bounds must satisfy minx < maxx and miny < maxy.", 422, "validation_error");
        }
        const aoi = await post<AOI>("/aois", {
          name: aoiName,
          description: "AOI created from the SARVEX analysis console",
          geometry: {
            type: "Polygon",
            coordinates: [
              [
                [minx, miny],
                [maxx, miny],
                [maxx, maxy],
                [minx, maxy],
                [minx, miny],
              ],
            ],
          },
        });
        aoiId = aoi.id;
        aois.reload();
      }

      const response = await post<JobCreateResponse>("/analyses", {
        analysis_type: analysisType,
        aoi_id: aoiId,
        product_ids: selectedProducts,
        parameters: makeParams(analysisType, parameters),
      });
      setMessage({
        kind: "ok",
        text: `Job ${response.job_id.slice(0, 8)}… queued${response.demo_mode ? " in demo mode" : ""}. Track it in the queue below.`,
      });
      jobs.reload();
    } catch (error) {
      setMessage({
        kind: "error",
        text:
          error instanceof ApiError
            ? `${error.message}${error.correlationId ? ` (ref ${error.correlationId.slice(0, 10)})` : ""}`
            : "Could not create the analysis job.",
      });
    } finally {
      setBusy(false);
    }
  }

  async function runNow(jobId: string) {
    try {
      await post<Job>(`/analyses/${jobId}/run`);
      jobs.reload();
      results.reload();
    } catch (error) {
      setMessage({
        kind: "error",
        text: error instanceof ApiError ? error.message : "Job execution failed.",
      });
    }
  }

  async function cancel(jobId: string) {
    try {
      await post<Job>(`/analyses/${jobId}/cancel`);
      jobs.reload();
    } catch (error) {
      setMessage({
        kind: "error",
        text: error instanceof ApiError ? error.message : "Cancellation failed.",
      });
    }
  }

  const resultByJob = useMemo(() => {
    const map = new Map<string, ResultSummary>();
    results.data?.items.forEach((result) => map.set(result.job_id, result));
    return map;
  }, [results.data]);

  return (
    <div className="page-stack">
      <SectionHeader
        kicker="Analysis console"
        title="Turn products into measured change"
        description="Choose a declared analysis mode, a compatible product stack and an AOI. The API records algorithm version, parameters, inputs and provenance for every run."
        actions={
          <Link className="btn btn-ghost" to="/explore">
            View measured layers →
          </Link>
        }
      />

      {message ? (
        <div className={`inline-notice ${message.kind === "error" ? "notice-error" : "notice-ok"}`}>
          {message.text}
          <button onClick={() => setMessage(null)} aria-label="Dismiss">×</button>
        </div>
      ) : null}

      <div className="analysis-grid">
        <form className="panel analysis-form" onSubmit={submit}>
          <div className="panel-head">
            <div>
              <div className="kicker">New job</div>
              <h2>Configure analysis</h2>
            </div>
            <span className="mode-pill mode-demo">{analysisType.replaceAll("_", " ")}</span>
          </div>

          <div className="field">
            <label htmlFor="analysis-type">Analysis type</label>
            <select id="analysis-type" value={analysisType} onChange={(event) => setAnalysisType(event.target.value)}>
              {Object.keys(COMPATIBILITY).map((type) => (
                <option key={type} value={type}>
                  {titleCase(type)}
                </option>
              ))}
            </select>
            <small className="field-help">
              Accepts {compatibleTypes.join(", ")} · minimum {minProducts} product{minProducts > 1 ? "s" : ""}.
            </small>
          </div>

          <div className="field">
            <label>Area of interest</label>
            <div className="segmented">
              <button type="button" className={!createAoi ? "active" : ""} onClick={() => setCreateAoi(false)}>
                Existing AOI
              </button>
              <button type="button" className={createAoi ? "active" : ""} onClick={() => setCreateAoi(true)}>
                Create from bbox
              </button>
            </div>
            {!createAoi ? (
              <select value={selectedAoi} onChange={(event) => setSelectedAoi(event.target.value)}>
                <option value="">Select an AOI…</option>
                {aois.data?.items.map((aoi) => (
                  <option key={aoi.id} value={aoi.id}>
                    {aoi.name} · {formatArea(aoi.area_m2)}
                  </option>
                ))}
              </select>
            ) : (
              <div className="aoi-create">
                <input value={aoiName} onChange={(event) => setAoiName(event.target.value)} placeholder="AOI name" />
                <input value={aoiBbox} onChange={(event) => setAoiBbox(event.target.value)} placeholder="minx,miny,maxx,maxy" />
                <small className="field-help">Bounds are WGS84. The polygon is created before the job is queued.</small>
              </div>
            )}
          </div>

          <div className="field">
            <div className="field-row">
              <label>Input products</label>
              <div className="field-actions">
                <button
                  type="button"
                  className="text-button"
                  onClick={() =>
                    setSelectedProducts(
                      compatibleProducts.slice(0, Math.max(minProducts, compatibleProducts.length)).map((product) => product.id),
                    )
                  }
                >
                  Select all compatible
                </button>
                <button type="button" className="text-button" onClick={() => setSelectedProducts([])}>
                  Clear
                </button>
              </div>
            </div>
            {products.loading ? (
              <LoadingBlock label="Loading products" rows={3} />
            ) : compatibleProducts.length ? (
              <div className="product-select-list">
                {compatibleProducts.map((product) => (
                  <label
                    key={product.id}
                    className={`product-select${selectedProducts.includes(product.id) ? " checked" : ""}`}
                  >
                    <input
                      type="checkbox"
                      checked={selectedProducts.includes(product.id)}
                      onChange={() => toggleProduct(product.id)}
                    />
                    <span className="product-main">
                      <span className="mono small">{product.product_id}</span>
                      <span className="product-meta">
                        {product.product_type} · {product.normalized_metadata.frequency_band || "—"} band ·{" "}
                        {product.normalized_metadata.polarization || "—"} ·{" "}
                        {formatDate(product.normalized_metadata.acquisition_start || product.created_at)}
                      </span>
                    </span>
                    {product.is_demo ? <DemoTag /> : null}
                  </label>
                ))}
              </div>
            ) : (
              <p className="fine-print">
                No ingested products match {compatibleTypes.join(", ")}. Search the catalog or upload a
                product first.
              </p>
            )}
            <small className="field-help">
              Selected {selectedProducts.length} of minimum {minProducts}.
            </small>
          </div>

          {PARAMS[analysisType]?.length ? (
            <div className="field">
              <label>Processing parameters</label>
              <div className="param-grid">
                {PARAMS[analysisType].map((field) => (
                  <div className="param-field" key={field.key}>
                    <span>{field.label}</span>
                    <input
                      value={parameters[field.key] ?? ""}
                      placeholder={field.placeholder}
                      inputMode="decimal"
                      onChange={(event) =>
                        setParameters((current) => ({ ...current, [field.key]: event.target.value }))
                      }
                    />
                    <small>{field.help}</small>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <p className="fine-print">
              This analysis runs with documented defaults. The full parameter set and algorithm
              version are recorded in provenance.
            </p>
          )}

          <div className="form-foot">
            <span className="fine-print">
              Unit expectations: backscatter/polarimetric dB, InSAR mm, offsets m. No model is allowed
              to fabricate a measurement.
            </span>
            <button className="btn btn-primary" type="submit" disabled={busy || !canRun}>
              {busy ? "Queueing…" : "Queue analysis"}
            </button>
          </div>
        </form>

        <aside className="panel">
          <div className="panel-head">
            <div>
              <div className="kicker">Scientific guardrails</div>
              <h2>Before you run</h2>
            </div>
          </div>
          <div className="guardrail-stack">
            <div>
              <span className="guardrail-index">01</span>
              <div>
                <strong>Input compatibility is enforced.</strong>
                <p>Deformation accepts GUNW/RUNW; backscatter accepts GCOV/GSLC. Incompatible stacks are rejected with a typed error.</p>
              </div>
            </div>
            <div>
              <span className="guardrail-index">02</span>
              <div>
                <strong>Minimum products matter.</strong>
                <p>Temporal analysis needs at least three epochs; a two-epoch change cannot establish a trend.</p>
              </div>
            </div>
            <div>
              <span className="guardrail-index">03</span>
              <div>
                <strong>Provenance is immutable.</strong>
                <p>Algorithm, version, parameters, input checksums, CRS, units and runtime are recorded with the run.</p>
              </div>
            </div>
            <div>
              <span className="guardrail-index">04</span>
              <div>
                <strong>Detection is not confirmation.</strong>
                <p>Events start as DETECTED or CLASSIFIED. Confirmation requires an independent external source.</p>
              </div>
            </div>
          </div>
          <div className="guardrail-note">
            <strong>Queue semantics.</strong> Jobs are persisted before execution. Inline workers
            process immediately in demo mode; external workers claim jobs atomically in production.
          </div>
        </aside>
      </div>

      <section className="panel">
        <div className="panel-head">
          <div>
            <div className="kicker">Processing queue</div>
            <h2>Jobs and progress</h2>
          </div>
          <span className="muted">{jobs.data?.total ?? 0} jobs</span>
        </div>
        {jobs.error ? (
          <ErrorState error={jobs.error} retry={jobs.reload} />
        ) : jobs.loading ? (
          <LoadingBlock label="Loading jobs" />
        ) : jobs.data?.items.length ? (
          <div className="job-list">
            {jobs.data.items.map((job) => {
              const result = resultByJob.get(job.id);
              return (
                <div className="job-row" key={job.id}>
                  <div className="job-main">
                    <div className="job-title">
                      <strong>{titleCase(job.analysis_type)}</strong>
                      <StatusBadge status={job.status} />
                      {job.is_demo ? <DemoTag /> : null}
                      <span className="mono small">{job.correlation_id.slice(0, 12)}</span>
                    </div>
                    <ProgressBar value={job.progress} label={job.current_stage || job.status} />
                    <div className="job-meta">
                      <span>Queued {formatDate(job.queued_at, true)}</span>
                      <span>{job.product_ids.length} products</span>
                      <span>stage {job.current_stage || "—"}</span>
                      {job.error ? <span className="error-text">{job.error}</span> : null}
                    </div>
                  </div>
                  <div className="job-actions">
                    {result ? (
                      <Link className="btn btn-sm btn-primary" to={`/analyses/${result.id}`}>
                        Open result
                      </Link>
                    ) : null}
                    {job.status === "QUEUED" ? (
                      <button className="btn btn-sm btn-ghost" onClick={() => void runNow(job.id)}>
                        Run now
                      </button>
                    ) : null}
                    {ACTIVE_STATES.has(job.status) && job.status !== "QUEUED" ? (
                      <button className="btn btn-sm btn-ghost" onClick={() => void cancel(job.id)}>
                        Cancel
                      </button>
                    ) : null}
                    <button
                      className="btn btn-sm btn-quiet"
                      onClick={() => setOpenLogs(openLogs === job.id ? null : job.id)}
                    >
                      {openLogs === job.id ? "Hide logs" : "Logs"}
                    </button>
                  </div>
                  {openLogs === job.id ? (
                    <div className="job-logs">
                      {job.logs.length ? (
                        job.logs.map((entry, index) => (
                          <div key={index} className={`log-line log-${String(entry.level).toLowerCase()}`}>
                            <span>{entry.ts ? new Date(entry.ts).toLocaleTimeString() : "—"}</span>
                            <span>{entry.level}</span>
                            <p>{entry.message}</p>
                          </div>
                        ))
                      ) : (
                        <p className="muted">No log entries yet.</p>
                      )}
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        ) : (
          <p className="muted">The queue is empty. Configure a job above to begin.</p>
        )}
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <div className="kicker">Outputs</div>
            <h2>Analysis results</h2>
          </div>
          <span className="muted">{results.data?.total ?? 0} results</span>
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
                  <th>Result</th>
                  <th>Units</th>
                  <th>Confidence</th>
                  <th>Uncertainty</th>
                  <th>Stage</th>
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
                    <td>{result.confidence !== null ? formatPercent(result.confidence) : "—"}</td>
                    <td>{formatNumber(result.uncertainty, 3)}</td>
                    <td>
                      <StageBadge stage={result.is_demo ? "DETECTED" : "DETECTED"} />
                    </td>
                    <td>{formatDate(result.created_at)}</td>
                    <td>
                      <Link className="row-link" to={`/analyses/${result.id}`}>Open</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">No results have been produced yet.</p>
        )}
      </section>
    </div>
  );
}
