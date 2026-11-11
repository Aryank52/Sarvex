import { useMemo, useRef, useState } from "react";
import { ApiError, post, request } from "../api/client";
import type {
  CatalogItem,
  CatalogSearchResponse,
  Dataset,
  IngestResponse,
  Observation,
  Page,
  Product,
} from "../api/types";
import { useApi } from "../hooks/useApi";
import {
  formatBytes,
  formatDate,
  formatNumber,
} from "../lib/format";
import {
  DemoTag,
  EmptyState,
  ErrorState,
  LoadingBlock,
  SectionHeader,
  StatusBadge,
} from "../components/States";

const CONNECTORS = [
  { id: "demo", label: "SARVEX demo", copy: "Synthetic, labelled fixtures for the Assam AOI." },
  { id: "asf", label: "NASA ASF", copy: "Public NISAR search. Authenticated download requires Earthdata." },
  { id: "bhoonidhi", label: "ISRO Bhoonidhi", copy: "Requires operator-supplied search endpoint and key." },
  { id: "stac", label: "STAC", copy: "Configured STAC search endpoints." },
  { id: "local", label: "Local", copy: "Operator-supplied local product directories." },
];

const PRODUCT_TYPES = ["GCOV", "GSLC", "GUNW", "RUNW", "RIFG", "RSLC", "ROFF", "GOFF"];

type SearchState = {
  loading: boolean;
  error: ApiError | null;
  result: CatalogSearchResponse | null;
};

type Notice = { kind: "ok" | "error"; text: string } | null;

export function Catalog() {
  const [tab, setTab] = useState<"products" | "datasets" | "observations">("products");
  const [connector, setConnector] = useState("demo");
  const [bbox, setBbox] = useState("91.55,26.05,91.95,26.32");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [selectedTypes, setSelectedTypes] = useState<string[]>(["GCOV", "GUNW"]);
  const [search, setSearch] = useState<SearchState>({ loading: false, error: null, result: null });
  const [ingesting, setIngesting] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice>(null);
  const [manifest, setManifest] = useState<{ datasetId: string; data: Record<string, unknown> | null } | null>(null);
  const [uploadType, setUploadType] = useState("GCOV");
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);

  const products = useApi<Page<Product>>("/products?limit=200");
  const datasets = useApi<Page<Dataset>>("/datasets?limit=200");
  const observations = useApi<Page<Observation>>("/observations?limit=200");

  const ingestedIds = useMemo(() => {
    const ids = new Set<string>();
    products.data?.items.forEach((product) => ids.add(product.product_id));
    return ids;
  }, [products.data]);

  async function runSearch(event: React.FormEvent) {
    event.preventDefault();
    setSearch({ loading: true, error: null, result: null });
    const bounds = bbox
      .split(",")
      .map((value) => Number(value.trim()))
      .filter((value) => Number.isFinite(value));
    try {
      const result = await post<CatalogSearchResponse>("/catalog/search", {
        connector,
        bbox: bounds.length === 4 ? bounds : null,
        start: start ? new Date(start).toISOString() : null,
        end: end ? new Date(end).toISOString() : null,
        product_types: selectedTypes,
        max_results: 100,
      });
      setSearch({ loading: false, error: null, result });
    } catch (error) {
      setSearch({
        loading: false,
        error:
          error instanceof ApiError
            ? error
            : new ApiError("Catalog search failed.", 0, "network_error"),
        result: null,
      });
    }
  }

  async function ingest(item: CatalogItem) {
    setIngesting(item.product_id);
    setNotice(null);
    try {
      const response = await post<IngestResponse>("/catalog/ingest", {
        connector,
        product_ref: item.product_id,
        product_type: item.product_type,
        catalog_item: item,
      });
      setNotice({
        kind: "ok",
        text: `Ingested ${response.product_type} as ${response.product_db_id.slice(0, 8)}… · validation ${response.validation_status}.`,
      });
      products.reload();
      datasets.reload();
      observations.reload();
    } catch (error) {
      setNotice({
        kind: "error",
        text:
          error instanceof ApiError
            ? `${error.message}${error.correlationId ? ` (ref ${error.correlationId.slice(0, 10)})` : ""}`
            : "Ingestion failed.",
      });
    } finally {
      setIngesting(null);
    }
  }

  async function openManifest(dataset: Dataset) {
    setManifest({ datasetId: dataset.dataset_id, data: null });
    try {
      const data = await request<Record<string, unknown>>(`/datasets/${dataset.dataset_id}/manifest`);
      setManifest({ datasetId: dataset.dataset_id, data });
    } catch (error) {
      setManifest({
        datasetId: dataset.dataset_id,
        data: { error: error instanceof ApiError ? error.message : "Manifest unavailable" },
      });
    }
  }

  async function upload(event: React.FormEvent) {
    event.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (!file) {
      setNotice({ kind: "error", text: "Choose a raster or HDF5 product before uploading." });
      return;
    }
    setUploading(true);
    setNotice(null);
    try {
      const form = new FormData();
      form.set("file", file);
      form.set("product_type", uploadType);
      form.set("provider", "Local Uploads");
      const response = await request<IngestResponse>("/catalog/upload", {
        method: "POST",
        body: form,
      });
      setNotice({
        kind: "ok",
        text: `Uploaded and validated as ${response.product_type}${response.is_demo ? " (file carries SARVEX demo tags)" : ""}.`,
      });
      if (fileRef.current) fileRef.current.value = "";
      products.reload();
      observations.reload();
      datasets.reload();
    } catch (error) {
      setNotice({
        kind: "error",
        text: error instanceof ApiError ? error.message : "Upload failed.",
      });
    } finally {
      setUploading(false);
    }
  }

  function toggleType(type: string) {
    setSelectedTypes((current) =>
      current.includes(type) ? current.filter((item) => item !== type) : [...current, type],
    );
  }

  return (
    <div className="page-stack">
      <SectionHeader
        kicker="Data catalog"
        title="Products, provenance and search"
        description="Search declared NISAR-family sources, ingest a product once, and keep its manifest, checksum and attribution attached forever."
        actions={
          <span className="data-mode-chip">
            {products.data ? `${products.data.total} products · ${datasets.data?.total ?? 0} datasets` : "loading catalog"}
          </span>
        }
      />

      {notice ? (
        <div className={`inline-notice ${notice.kind === "error" ? "notice-error" : "notice-ok"}`}>
          {notice.text}
          <button onClick={() => setNotice(null)} aria-label="Dismiss">
            ×
          </button>
        </div>
      ) : null}

      <section className="panel">
        <div className="panel-head">
          <div>
            <div className="kicker">Remote and local discovery</div>
            <h2>Search a connector</h2>
          </div>
          <div className="connector-pills">
            {CONNECTORS.map((item) => (
              <button
                key={item.id}
                className={`connector-pill${connector === item.id ? " active" : ""}`}
                onClick={() => setConnector(item.id)}
                title={item.copy}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>

        <p className="connector-copy">{CONNECTORS.find((item) => item.id === connector)?.copy}</p>

        <form className="search-form" onSubmit={runSearch}>
          <div className="field">
            <label htmlFor="bbox">Bounding box (minx, miny, maxx, maxy)</label>
            <input id="bbox" value={bbox} onChange={(event) => setBbox(event.target.value)} placeholder="91.55,26.05,91.95,26.32" />
          </div>
          <div className="field">
            <label htmlFor="start">Start date</label>
            <input id="start" type="date" value={start} onChange={(event) => setStart(event.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="end">End date</label>
            <input id="end" type="date" value={end} onChange={(event) => setEnd(event.target.value)} />
          </div>
          <div className="field field-types">
            <label>Product types</label>
            <div className="chip-row">
              {PRODUCT_TYPES.map((type) => (
                <button
                  type="button"
                  key={type}
                  className={`chip${selectedTypes.includes(type) ? " active" : ""}`}
                  onClick={() => toggleType(type)}
                >
                  {type}
                </button>
              ))}
            </div>
          </div>
          <button className="btn btn-primary" type="submit" disabled={search.loading}>
            {search.loading ? "Searching…" : "Search source"}
          </button>
        </form>

        {search.error ? <ErrorState error={search.error} /> : null}
        {search.result ? (
          <div className="search-results">
            <div className="search-summary">
              <span>
                <strong>{search.result.total}</strong> products from <strong>{search.result.connector}</strong>
              </span>
              <span className={`mode-pill mode-${search.result.data_mode.toLowerCase()}`}>{search.result.data_mode}</span>
              {search.result.demo_fallback ? <span className="warn-pill">demo fallback</span> : null}
            </div>
            {search.result.warning ? <div className="inline-warning">{search.result.warning}</div> : null}
            {search.result.items.length ? (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Product</th>
                      <th>Type</th>
                      <th>Band / pol</th>
                      <th>Acquired</th>
                      <th>Source</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {search.result.items.map((item) => {
                      const already = ingestedIds.has(item.product_id);
                      return (
                        <tr key={`${item.provider}-${item.product_id}`}>
                          <td>
                            <span className="mono small">{item.product_id}</span>
                            {item.is_demo ? <DemoTag /> : null}
                          </td>
                          <td>{item.product_type}</td>
                          <td>
                            {item.frequency_band || "—"} / {item.polarization || "—"}
                          </td>
                          <td>{formatDate(item.acquisition_start)}</td>
                          <td>{item.provider}</td>
                          <td className="align-right">
                            {connector === "local" ? (
                              <span className="muted">use upload</span>
                            ) : (
                              <button
                                className="btn btn-sm btn-ghost"
                                disabled={already || ingesting === item.product_id}
                                onClick={() => void ingest(item)}
                              >
                                {already ? "In catalog" : ingesting === item.product_id ? "Ingesting…" : "Ingest"}
                              </button>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState title="No matching products">
                The connector returned no items. SARVEX does not fill an empty live search with
                renamed synthetic records unless explicit demo fallback is enabled.
              </EmptyState>
            )}
          </div>
        ) : null}
      </section>

      <div className="catalog-grid">
        <section className="panel">
          <div className="panel-head">
            <div>
              <div className="kicker">Local operations</div>
              <h2>Upload a product</h2>
            </div>
          </div>
          <p className="panel-copy">
            Files are validated by the adapter registry before cataloging. Duplicate checksums are
            rejected rather than silently duplicated.
          </p>
          <form className="upload-form" onSubmit={upload}>
            <div className="field">
              <label htmlFor="upload-file">Raster / HDF5 file</label>
              <input
                id="upload-file"
                ref={fileRef}
                type="file"
                accept=".tif,.tiff,.cog,.h5,.hdf5,.he5,.nc,.img,.vrt"
              />
            </div>
            <div className="field">
              <label htmlFor="upload-type">Product type</label>
              <select id="upload-type" value={uploadType} onChange={(event) => setUploadType(event.target.value)}>
                {PRODUCT_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </select>
            </div>
            <button className="btn btn-primary" type="submit" disabled={uploading}>
              {uploading ? "Validating…" : "Upload & ingest"}
            </button>
          </form>
          <p className="fine-print">
            Accepted: GeoTIFF, COG, HDF5/HDF-EOS5 and NetCDF. Demo files remain tagged as synthetic;
            tags are never stripped.
          </p>
        </section>

        <section className="panel">
          <div className="panel-head">
            <div>
              <div className="kicker">Provenance</div>
              <h2>Catalog rules</h2>
            </div>
          </div>
          <ul className="rule-list">
            <li>
              <strong>One checksum, one product.</strong> Duplicate ingestion is a conflict, not a new
              observation.
            </li>
            <li>
              <strong>Attribution is mandatory.</strong> Provider, license and citation are carried in
              the manifest and reports.
            </li>
            <li>
              <strong>Demo tags survive.</strong> Synthetic fixtures are labelled at the file,
              catalog, analysis, event and report levels.
            </li>
            <li>
              <strong>Missing credentials stay missing.</strong> Bhoonidhi is reported unconfigured
              until an operator supplies a search endpoint and key.
            </li>
          </ul>
        </section>
      </div>

      <section className="panel">
        <div className="panel-tabs">
          {(
            [
              ["products", `Products (${products.data?.total ?? "…"})`],
              ["datasets", `Datasets (${datasets.data?.total ?? "…"})`],
              ["observations", `Observations (${observations.data?.total ?? "…"})`],
            ] as const
          ).map(([id, label]) => (
            <button key={id} className={`tab${tab === id ? " active" : ""}`} onClick={() => setTab(id)}>
              {label}
            </button>
          ))}
        </div>

        {tab === "products" ? (
          products.error ? (
            <ErrorState error={products.error} retry={products.reload} />
          ) : products.loading ? (
            <LoadingBlock label="Loading products" />
          ) : (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Product</th>
                    <th>Type</th>
                    <th>Band / pol</th>
                    <th>Provider</th>
                    <th>Validation</th>
                    <th>Adapter</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {products.data?.items.map((product) => (
                    <tr key={product.id}>
                      <td>
                        <span className="mono small">{product.product_id}</span>
                        {product.is_demo ? <DemoTag /> : null}
                      </td>
                      <td>{product.product_type}</td>
                      <td>
                        {product.normalized_metadata.frequency_band || "—"} /{" "}
                        {product.normalized_metadata.polarization || "—"}
                      </td>
                      <td>{product.provider}</td>
                      <td>
                        <StatusBadge status={product.validation_status.split(":")[0]} />
                        <span className="fine-print block">{product.validation_status}</span>
                      </td>
                      <td className="mono small">
                        {product.adapter_name} v{product.adapter_version}
                      </td>
                      <td>{formatDate(product.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        ) : null}

        {tab === "datasets" ? (
          datasets.error ? (
            <ErrorState error={datasets.error} retry={datasets.reload} />
          ) : datasets.loading ? (
            <LoadingBlock label="Loading datasets" />
          ) : (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Dataset</th>
                    <th>Mission</th>
                    <th>Provider</th>
                    <th>License</th>
                    <th>Validation</th>
                    <th>Manifest</th>
                  </tr>
                </thead>
                <tbody>
                  {datasets.data?.items.map((dataset) => (
                    <tr key={dataset.id}>
                      <td>
                        <span className="mono small">{dataset.dataset_id}</span>
                        {dataset.is_demo ? <DemoTag /> : null}
                      </td>
                      <td>{dataset.mission}</td>
                      <td>{dataset.provider}</td>
                      <td className="truncate">{dataset.license}</td>
                      <td>{dataset.validation_status}</td>
                      <td>
                        <button className="btn btn-sm btn-ghost" onClick={() => void openManifest(dataset)}>
                          Inspect
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        ) : null}

        {tab === "observations" ? (
          observations.error ? (
            <ErrorState error={observations.error} retry={observations.reload} />
          ) : observations.loading ? (
            <LoadingBlock label="Loading observations" />
          ) : (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Observation</th>
                    <th>Type</th>
                    <th>Acquired</th>
                    <th>Band</th>
                    <th>Polarization</th>
                    <th>Orbit / track</th>
                    <th>Pass</th>
                  </tr>
                </thead>
                <tbody>
                  {observations.data?.items.map((observation) => (
                    <tr key={observation.id}>
                      <td>
                        <span className="mono small">{observation.product_id}</span>
                        {observation.is_demo ? <DemoTag /> : null}
                      </td>
                      <td>{observation.product_type}</td>
                      <td>{formatDate(observation.acquisition_start, true)}</td>
                      <td>
                        {observation.frequency_band || "—"}
                        {observation.frequency_hz ? (
                          <span className="fine-print block">{formatNumber(observation.frequency_hz / 1e9, 3)} GHz</span>
                        ) : null}
                      </td>
                      <td>{observation.polarization || "—"}</td>
                      <td>
                        {observation.orbit ?? "—"} / {observation.track ?? "—"}
                      </td>
                      <td>{observation.pass_direction || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        ) : null}
      </section>

      {manifest ? (
        <div className="modal-backdrop" onClick={() => setManifest(null)}>
          <div className="modal" onClick={(event) => event.stopPropagation()}>
            <div className="modal-head">
              <div>
                <div className="kicker">Immutable manifest</div>
                <h2>{manifest.datasetId}</h2>
              </div>
              <button className="icon-btn" onClick={() => setManifest(null)} aria-label="Close manifest">
                ×
              </button>
            </div>
            {manifest.data ? (
              <pre className="json-block">{JSON.stringify(manifest.data, null, 2)}</pre>
            ) : (
              <LoadingBlock label="Loading manifest" rows={8} />
            )}
            <p className="fine-print">
              Checksums, source attribution and license travel with the product into analyses and
              reports. {formatBytes(0) === "0 B" ? "" : ""}
            </p>
          </div>
        </div>
      ) : null}
    </div>
  );
}
