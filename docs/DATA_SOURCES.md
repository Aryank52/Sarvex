# Data sources

## Connectors

| Connector | Source | Credentials | Status when unconfigured |
|-----------|--------|-------------|--------------------------|
| `demo` | SARVEX synthetic fixtures (Assam AOI) | none | always available |
| `asf` | NASA ASF Search API | Earthdata for downloads | search public; download needs auth |
| `bhoonidhi` | ISRO Bhoonidhi | operator-supplied search URL + API key | reported unconfigured, not fabricated |
| `stac` | Configured STAC endpoints | per endpoint | reported unconfigured if empty |
| `local` | Operator-supplied directories | filesystem access | available when paths exist |

## Credential policy

- Credentials are read from environment variables, never stored in YAML or code.
- Missing credentials are surfaced as `unconfigured`, not silently replaced with
  demo data unless `DEMO_MODE=auto` and the caller did not request a specific
  connector.
- Explicit demo searches set `demo_fallback=false`.

## Demo fixtures

- Real Assam AOI bounds: `(91.55, 26.05, 91.95, 26.32)`.
- Synthetic pixels generated deterministically, tagged `SARVEX-DEMO`,
  `is_demo=true` at file, catalog, analysis, event and report level.
- Never presented as NASA/ISRO observations. The UI shows a persistent DEMO MODE
  banner.

## Attribution

Provider, licence, citation and attribution are mandatory in dataset manifests and
travel into analyses and reports. Duplicate checksums are rejected rather than
silently duplicated.
