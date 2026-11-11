# Demo mode

## Policy

- `DEMO_MODE` ∈ {`auto`, `on`, `off`}.
- When `on`, the platform seeds synthetic Assam fixtures and reports
  `DEMO MODE` everywhere.
- Fixtures are SARVEX-authored synthetics with real Assam AOI bounds and
  synthetic pixels. They are never presented as NASA/ISRO data.
- `is_demo=true` is carried at file, product, analysis, event and report level.

## Confirmation gate

- Demo events cannot be confirmed (API returns 422 `validation_error`).
- Synthetic evidence is rejected.
- A URL or citation is mandatory for confirmation.
- Confirmation creates an `EvidenceItem`.

## Auto mode

In `auto`, live connectors are used when configured; otherwise fixtures are used
and clearly labelled. Explicit demo searches set `demo_fallback=false`.
