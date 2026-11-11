export type Page<T> = {
  items: T[];
  total: number;
  limit: number;
  offset: number;
};

export type ErrorBody = {
  code?: string;
  message?: string;
  detail?: unknown;
  correlation_id?: string | null;
};

export type Health = {
  status: string;
  app: string;
  version: string;
  code_version: string;
  environment: string;
  time: string;
  database: {
    backend: string;
    postgis: boolean;
    pgvector: boolean;
    healthy: boolean;
    error: string | null;
  };
  object_storage: { backend: string };
  demo_mode: {
    setting: string;
    effective_data_mode: string;
    demo_products: number;
    banner: string | null;
  };
  models: {
    configured: Record<string, unknown>;
    active_llm: Record<string, unknown>;
    degraded_by_default: boolean;
  };
  isce3: { available: boolean; status: string; detail?: string };
  rag: {
    documents: number;
    chunks: number;
    embeddings: number;
    embedding_model?: string;
    reranker_model?: string;
    llm_model?: string;
    demo_documents?: number;
  };
  worker: { inline: boolean; mode: string };
  offline_mode: boolean;
};

export type Capabilities = {
  analysis_types: { type: string; modes: string[]; min_products: number }[];
  connectors: string[];
  product_types: string[];
  frequency_bands: string[];
  models: ModelSummary;
  isce3: { available: boolean; status: string };
  offline_mode: boolean;
  demo_mode: string;
  storage: { database: string; objects: string };
};

export type ModelSummary = {
  embedding: {
    name: string;
    provider: string;
    dimension: number;
    semantic?: boolean;
    degraded?: boolean;
  };
  reranker: { name: string; provider: string; degraded?: boolean };
  llm: { name: string; provider: string; degraded?: boolean; status?: string };
  change_detection?: { name: string; provider: string; version?: string };
  storage_capacity: number;
  [key: string]: unknown;
};

export type ModelInfo = {
  category: string;
  name: string;
  provider: string;
  version: string;
  task: string | null;
  framework: string | null;
  status: string;
  is_default: boolean;
  capabilities: Record<string, unknown>;
  health: Record<string, unknown>;
};

export type EventSummary = {
  id: string;
  event_type: string;
  taxonomy_stage: string;
  classification_method: string | null;
  classification_confidence: number | null;
  geometry: GeoJSON.Geometry;
  start_time: string | null;
  end_time: string | null;
  area_m2: number | null;
  magnitude: number | null;
  magnitude_unit: string | null;
  confidence: number | null;
  uncertainty: number | null;
  persistence: number | null;
  severity: number | null;
  priority: number | null;
  status: string;
  summary: string;
  run_id: string | null;
  model_run_id: string | null;
  properties: Record<string, unknown>;
  is_demo: boolean;
  created_at: string;
};

export type Evidence = {
  id: string;
  source_type: string;
  title: string;
  url: string | null;
  citation: string | null;
  snippet: string | null;
  evidence_metadata: Record<string, unknown>;
  confidence: number | null;
  is_demo: boolean;
};

export type ContextLayer = {
  id: string;
  layer_type: string;
  name: string;
  geometry: GeoJSON.Geometry | null;
  provider: string;
  license: string;
  source: string;
  version: string | null;
  crs: string;
  layer_date: string | null;
  properties: Record<string, unknown>;
  is_demo: boolean;
};

export type Exposure = {
  id: string;
  event_id: string;
  asset_id: string;
  distance_m: number;
  overlap_ratio: number;
  exposure_score: number;
  rationale: string;
  asset?: Asset | null;
};

export type Asset = {
  id: string;
  asset_type: string;
  name: string;
  geometry: GeoJSON.Geometry;
  provider: string;
  license: string;
  source: string;
  properties: Record<string, unknown>;
  is_demo: boolean;
};

export type EventDetail = EventSummary & {
  observation_ids: string[];
  evidence_ids: string[];
  context_ids: string[];
  exposures: Exposure[];
};

export type EventFeatureCollection = GeoJSON.FeatureCollection<
  GeoJSON.Geometry,
  {
    event_type: string;
    taxonomy_stage: string;
    status: string;
    confidence: number | null;
    uncertainty: number | null;
    area_m2: number | null;
    magnitude: number | null;
    magnitude_unit: string | null;
    severity: number | null;
    priority: number | null;
    summary: string;
    is_demo: boolean;
    start_time: string | null;
    end_time: string | null;
  }
> & {
  metadata: { count: number; demo_mode: boolean; notice: string | null };
};

export type ResultSummary = {
  id: string;
  run_id: string;
  job_id: string;
  aoi_id: string | null;
  result_type: string;
  summary: string;
  statistics: Record<string, unknown>;
  artifacts: Record<string, unknown>;
  layer_metadata: Record<string, unknown>;
  units: string | null;
  confidence: number | null;
  uncertainty: number | null;
  is_demo: boolean;
  created_at: string;
};

export type ProcessingRun = {
  id: string;
  job_id: string;
  analysis_type: string;
  algorithm: string;
  algorithm_version: string;
  parameters: Record<string, unknown>;
  input_product_ids: string[];
  observation_ids: string[];
  dataset_ids: string[];
  model_name: string | null;
  model_version: string | null;
  crs: string;
  units: string | null;
  code_version: string;
  provenance: Record<string, unknown>;
  status: string;
  started_at: string;
  finished_at: string | null;
};

export type ResultDetail = ResultSummary & {
  run: ProcessingRun | null;
  events: EventSummary[];
};

export type Feature = {
  id: string;
  result_id: string;
  feature_type: string;
  geometry: GeoJSON.Geometry | null;
  value: number | null;
  unit: string | null;
  uncertainty: number | null;
  confidence: number | null;
  properties: Record<string, unknown>;
};

export type LayerLegendStop = {
  value: number;
  color: string;
  label: string;
};

export type LayerMeta = {
  name: string;
  layer?: string;
  title: string;
  units: string;
  method: string;
  source: string;
  product_ids: string[];
  dates: string[];
  ramp: string;
  vmin: number;
  vmax: number;
  bbox: number[];
  crs: string | null;
  width: number;
  height: number;
  raster_uri: string;
  png_uri: string;
  image_coordinates: [number, number][];
  legend: LayerLegendStop[];
  legend_title: string;
  valid_fraction: number;
  extra: Record<string, unknown>;
};

export type LayersResponse = {
  result_id: string;
  is_demo: boolean;
  layers: LayerMeta[];
  limitations: string[];
  provenance: Record<string, unknown>;
};

export type TimeSeries = {
  id: string;
  aoi_id: string | null;
  result_id: string | null;
  event_id: string | null;
  series_type: string;
  unit: string;
  points: { date?: string; value: number; [key: string]: unknown }[];
  trend: Record<string, unknown>;
  change_points: Record<string, unknown>[];
  gaps: Record<string, unknown>[];
  confidence: number | null;
  is_demo: boolean;
  created_at: string;
};

export type Job = {
  id: string;
  analysis_type: string;
  status: string;
  aoi_id: string | null;
  product_ids: string[];
  parameters: Record<string, unknown>;
  progress: number;
  current_stage: string | null;
  error: string | null;
  correlation_id: string;
  logs: { ts: string | null; level: string; message: string; [key: string]: unknown }[];
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
  is_demo: boolean;
  created_at: string;
};

export type JobCreateResponse = {
  job_id: string;
  status: string;
  correlation_id: string;
  demo_mode: boolean;
};

export type AOI = {
  id: string;
  name: string;
  description: string | null;
  geometry: GeoJSON.Geometry;
  bbox: number[];
  area_m2: number | null;
  crs: string;
  created_at: string;
  updated_at: string;
};

export type Dataset = {
  id: string;
  dataset_id: string;
  provider: string;
  product_id: string;
  product_type: string;
  mission: string;
  satellite: string | null;
  source_url: string | null;
  license: string | null;
  citation: string | null;
  attribution: string | null;
  validation_status: string;
  is_demo: boolean;
  manifest: Record<string, unknown>;
  created_at: string;
};

export type Observation = {
  id: string;
  dataset_id: string;
  product_id: string;
  product_type: string;
  acquisition_start: string;
  acquisition_end: string | null;
  orbit: number | null;
  pass_direction: string | null;
  track: number | null;
  frame: number | null;
  frequency_band: string | null;
  frequency_hz: number | null;
  polarization: string | null;
  wavelength_m: number | null;
  crs: string | null;
  bbox: number[];
  geometry: GeoJSON.Geometry | null;
  spatial_resolution_m: number | null;
  units: string | null;
  processing_baseline: string | null;
  quality: Record<string, unknown>;
  calibration_status: string | null;
  provider: string;
  is_demo: boolean;
};

export type Product = {
  id: string;
  observation_id: string;
  product_id: string;
  product_type: string;
  provider: string;
  object_uri: string | null;
  file_format: string | null;
  file_size: number | null;
  checksum: string | null;
  source_url: string | null;
  normalized_metadata: {
    frequency_band?: string;
    frequency_hz?: number;
    polarization?: string;
    wavelength_m?: number;
    acquisition_start?: string;
    units?: string;
    [key: string]: unknown;
  };
  manifest: Record<string, unknown>;
  validation_status: string;
  adapter_name: string;
  adapter_version: string;
  is_demo: boolean;
  created_at: string;
};

export type CatalogItem = {
  provider: string;
  product_id: string;
  product_type: string;
  acquisition_start: string | null;
  bbox: number[] | null;
  frequency_band: string | null;
  polarization: string | null;
  source_url: string | null;
  file_format: string | null;
  size_bytes: number | null;
  is_demo: boolean;
  extra: Record<string, unknown>;
};

export type CatalogSearchResponse = {
  items: CatalogItem[];
  connector: string;
  demo_fallback: boolean;
  warning: string | null;
  data_mode: string;
  total: number;
};

export type IngestResponse = {
  dataset_id: string;
  observation_id: string;
  product_db_id: string;
  product_type: string;
  validation_status: string;
  is_demo: boolean;
};

export type Citation = {
  id: string;
  chunk_id: string;
  document_id: string;
  title: string;
  url: string | null;
  publisher: string | null;
  author: string | null;
  publication_date: string | null;
  section: string | null;
  page: number | null;
  document_type: string;
  scientific_topic: string | null;
  source_priority: number;
  snippet: string;
  score: number;
  is_demo: boolean;
};

export type CopilotResponse = {
  session_id: string;
  answer: string;
  observed_facts: string[];
  derived_findings: string[];
  interpretations: string[];
  uncertainties: string[];
  evidence: {
    citation_id: string;
    title: string;
    url: string | null;
    publisher: string | null;
    publication_date: string | null;
    snippet: string;
    is_demo: boolean;
  }[];
  confidence: string;
  limitations: string[];
  taxonomy_stage: string;
  citations_validated: boolean;
  unsupported_claims: string[];
  model: string;
  model_version: string;
  provider: string;
  degraded: boolean;
  demo_mode: boolean;
  retrieval: Record<string, unknown>;
  analysis_context: Record<string, unknown>;
};

export type CopilotSession = {
  id: string;
  title: string;
  aoi_id: string | null;
  event_id: string | null;
  result_id: string | null;
  messages: number;
  updated_at: string;
};

export type Report = {
  id: string;
  title: string;
  report_type: string;
  result_id: string | null;
  event_id: string | null;
  format: string;
  content: string;
  artifact_uri: string | null;
  provenance: Record<string, unknown>;
  created_at: string;
};

export type ReportSummary = Omit<Report, "content" | "provenance">;

export type EventStats = {
  total: number;
  demo: number;
  by_type: Record<string, number>;
  by_status: Record<string, number>;
  by_taxonomy_stage: Record<string, number>;
};
