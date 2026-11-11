# SAR processing

## Algorithms (deterministic baselines)

- **Backscatter change**: temporal median + robust MAD z-score on dB scale;
  connected components, area cleanup, morphology. Units: dB.
- **InSAR deformation**: phase difference to LOS displacement, coherence
  masking, robust statistics, relative AOI-median reference. Units: mm.
  Algorithm id: `gunw_los_displacement_mad_v1`.
- **Polarimetric**: dual-pol VV/VH ratio comparison; rule-based candidate
  categories are hypotheses. Units: dB ratio.
- **Offsets**: phase correlation of amplitude images with sub-pixel shift.
  Units: m.
- **Timeseries**: Theil-Sen robust trend, rolling median, gap detection, CUSUM
  change points. Units: dB (backscatter) or as configured.

## Units and uncertainty

Every statistic carries units. Uncertainty is reported alongside measurements.
Confidence is detection/answer confidence, never a hazard probability.

## Limitations (always recorded)

- LOS displacement only; no 2-D/3-D decomposition.
- Relative to AOI median displacement.
- No orbital ramp estimation in the baseline.
- Low coherence masks displacement.
- Category labels are hypotheses requiring validation.
- Spatial proximity is not causality.

## ISCE3

ISCE3 is probed via `isce3` adapter. When unavailable, SARVEX uses its
deterministic baselines and reports the adapter status. No silent fallback.
