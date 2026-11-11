import { Link } from "react-router-dom";
import { useApi } from "../hooks/useApi";
import type { Capabilities, Health } from "../api/types";
import { titleCase } from "../lib/format";
import {
  Kpi,
  SectionHeader,
  StageBadge,
} from "../components/States";

const EVIDENCE_STAGES = [
  ["OBSERVED", "Values as measured by an instrument or retrieved passage. No interpretation attached."],
  ["DERIVED", "A quantity computed from observations with a stated algorithm and units."],
  ["DETECTED", "A region flagged by a statistical procedure and a stated threshold."],
  ["CLASSIFIED", "A rule or model label. Still an assertion, not a finding."],
  ["HYPOTHESIZED", "A proposed explanation. Requires independent validation."],
  ["CONTEXTUALIZED", "Related external context. Proximity is not causality."],
  ["CONFIRMED", "Supported by independent, authoritative evidence attached to the record."],
];

const PIPELINE = [
  ["Ingest", "Validate", "Adapters confirm file format, checksums, metadata and attribution before cataloging."],
  ["Backscatter", "Detect", "Temporal median plus robust MAD z-score on dB scale, with connected components and area cleanup."],
  ["InSAR", "Quantify", "Phase difference to LOS displacement, coherence masking, robust statistics and relative reference."],
  ["Polarimetry", "Characterise", "Dual-pol VV/VH ratio comparison with rule-based, explicitly hypothetical categories."],
  ["Offsets", "Measure", "Phase correlation of amplitude images with sub-pixel shift estimates and a magnitude."],
  ["Timeseries", "Trend", "Theil-Sen robust trend, rolling median, gap detection and CUSUM change points."],
  ["Events", "Stage", "Detections are emitted with stage, confidence, uncertainty, area and magnitude."],
  ["Copilot", "Explain", "Read-only context and retrieved passages. Citations are validated before display."],
];

const GUARDRAILS = [
  ["No invented science", "The language model explains supplied measurements; it cannot add a measurement, change a unit or confirm an event."],
  ["Units everywhere", "Every statistic carries units. Reports and API responses retain them; the UI never strips them."],
  ["Uncertainty is first-class", "Displacement, detection and answer confidence are separate quantities. None is a hazard probability."],
  ["Provenance is immutable", "Algorithm, version, parameters, inputs, CRS, units, timestamps and code version are stored with the run."],
  ["Demo is explicit", "Synthetic fixtures are tagged at file, product, analysis, event and report level. They are never presented as NASA/ISRO data."],
  ["Models are configuration", "Embeddings, reranker and language model are resolved from config/models.yaml through a provider abstraction."],
  ["No silent truncation", "Vectors above the configured pgvector capacity are rejected. Shorter vectors are zero-padded without changing similarity."],
  ["Confirmation gate", "Demo events cannot be confirmed. Synthetic evidence is rejected. A URL or citation is mandatory."],
];

export function Method() {
  const health = useApi<Health>("/health");
  const capabilities = useApi<Capabilities>("/capabilities");

  return (
    <div className="page-stack">
      <SectionHeader
        kicker="Method and guardrails"
        title="How SARVEX turns radar into evidence"
        description="Measurements come from declared algorithms and validated products. Explanations come from retrieval. Confirmation comes only from independent external evidence."
      />

      <div className="kpi-grid kpi-grid-five">
        <Kpi label="Evidence stages" value={7} detail="OBSERVED through CONFIRMED" tone="cyan" />
        <Kpi label="Analysis modes" value={capabilities.data?.analysis_types.length ?? "…"} detail="Declared in /capabilities" tone="violet" />
        <Kpi label="Connectors" value={capabilities.data?.connectors.length ?? "…"} detail="ASF, Bhoonidhi, STAC, local, demo" tone="amber" />
        <Kpi label="Storage" value={health.data?.database.backend || "…"} detail="Postgres/PostGIS/pgvector or SQLite fallback" tone="green" />
        <Kpi label="Provider mode" value={health.data?.offline_mode ? "offline-safe" : "network"} detail="No silent degradation" tone="cyan" />
      </div>

      <section className="panel">
        <div className="panel-head">
          <div>
            <div className="kicker">Evidence ladder</div>
            <h2>What a stage means</h2>
          </div>
          <Link className="text-link" to="/copilot">
            Try the copilot →
          </Link>
        </div>
        <div className="stage-ladder">
          {EVIDENCE_STAGES.map(([stage, copy], index) => (
            <div className="ladder-step" key={stage}>
              <span className="ladder-index">{index + 1}</span>
              <StageBadge stage={stage} />
              <p>{copy}</p>
            </div>
          ))}
        </div>
        <p className="fine-print">
          Stages are visible in the API, the UI and generated reports. A detection is never
          automatically promoted.
        </p>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <div className="kicker">Processing chain</div>
            <h2>From product to event</h2>
          </div>
        </div>
        <div className="method-grid">
          {PIPELINE.map(([title, verb, copy]) => (
            <div className="method-card" key={title}>
              <div className="method-card-head">
                <span className="method-verb">{verb}</span>
                <strong>{title}</strong>
              </div>
              <p>{copy}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <div className="kicker">Declared capabilities</div>
            <h2>Analysis modes</h2>
          </div>
        </div>
        {capabilities.data ? (
          <div className="capability-list">
            {capabilities.data.analysis_types.map((item) => (
              <div className="capability" key={item.type}>
                <div className="capability-type">{titleCase(item.type)}</div>
                <div className="capability-modes">
                  {item.modes.map((mode) => (
                    <span key={mode}>{mode}</span>
                  ))}
                </div>
                <div className="capability-min">min {item.min_products} product{item.min_products > 1 ? "s" : ""}</div>
              </div>
            ))}
          </div>
        ) : (
          <p className="muted">Loading capabilities…</p>
        )}
        <div className="integrity-grid">
          <div>
            <span>Frequency bands</span>
            <strong>{capabilities.data?.frequency_bands.join(", ") || "—"}</strong>
          </div>
          <div>
            <span>Product types</span>
            <strong>{capabilities.data?.product_types.length || "—"}</strong>
          </div>
          <div>
            <span>ISCE3</span>
            <strong>{capabilities.data?.isce3.available ? "available" : "not installed"}</strong>
          </div>
          <div>
            <span>Offline mode</span>
            <strong>{capabilities.data?.offline_mode ? "on" : "off"}</strong>
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <div className="kicker">Scientific guardrails</div>
            <h2>What SARVEX refuses to do</h2>
          </div>
        </div>
        <div className="guardrail-stack">
          {GUARDRAILS.map(([title, copy], index) => (
            <div key={title}>
              <span className="guardrail-index">{String(index + 1).padStart(2, "0")}</span>
              <div>
                <strong>{title}.</strong>
                <p>{copy}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <div className="kicker">Radar literacy</div>
            <h2>What the measurements mean</h2>
          </div>
        </div>
        <div className="radar-grid">
          <div>
            <strong>Backscatter (dB)</strong>
            <p>
              Radar reflectivity of the surface. Change in dB relates to roughness, moisture and
              vegetation structure. It is a measurement, not a land-cover label.
            </p>
          </div>
          <div>
            <strong>LOS displacement (mm)</strong>
            <p>
              Line-of-sight change between two SAR acquisitions. Relative to an AOI median reference.
              It is not a 2-D/3-D vector and not a hazard assessment.
            </p>
          </div>
          <div>
            <strong>Coherence</strong>
            <p>
              Phase stability between acquisitions. Low coherence masks displacement. It is a data
              quality indicator, not a damage indicator.
            </p>
          </div>
          <div>
            <strong>Polarimetric ratio (dB)</strong>
            <p>
              VV/VH comparison. Candidate categories are rule-based hypotheses from dual-pol
              observables and require independent validation.
            </p>
          </div>
          <div>
            <strong>Image offsets (m)</strong>
            <p>
              Estimated sub-pixel shift between amplitude images. A measurement of geometric
              displacement, not an interpretation of cause.
            </p>
          </div>
          <div>
            <strong>Trend (dB/year)</strong>
            <p>
              Robust Theil-Sen trend across epochs. Describes direction and rate of change in the
              observed signal, not an ecological or hazard conclusion.
            </p>
          </div>
        </div>
        <p className="fine-print">
          Category labels such as flood or landslide are hypotheses. SARVEX never presents them as
          confirmed without independent evidence.
        </p>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <div className="kicker">Model registry</div>
            <h2>Declared providers</h2>
          </div>
          <Link className="text-link" to="/models">
            Open registry →
          </Link>
        </div>
        <p className="panel-copy">
          No model name is hard-coded in business logic. Embeddings, reranker and language model
          are resolved from <code>backend/config/models.yaml</code>. Offline-safe defaults keep the
          platform honest when providers are absent.
        </p>
        <div className="integrity-grid">
          <div>
            <span>Embedding</span>
            <strong>{health.data?.models.active_llm?.name ? "configured" : "offline-safe"}</strong>
          </div>
          <div>
            <span>Degraded by default</span>
            <strong>{health.data?.models.degraded_by_default ? "yes" : "no"}</strong>
          </div>
          <div>
            <span>Vector capacity</span>
            <strong>1536</strong>
          </div>
          <div>
            <span>RAG documents</span>
            <strong>{health.data?.rag.documents ?? 0}</strong>
          </div>
        </div>
      </section>
    </div>
  );
}
