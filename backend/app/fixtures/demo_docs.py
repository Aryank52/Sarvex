"""SARVEX-authored demo knowledge documents.

These are NOT NASA or ISRO documents. They are short, carefully worded summaries
of standard SAR/InSAR concepts, written for the offline demo. Production
deployments should ingest official NISAR/ISRO documentation, which then outranks
these notes via ``source_priority``.

Every entry is ingested with ``is_demo=True`` and ``source_priority=7``.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DemoDocument:
    title: str
    topic: str
    text: str


DEMO_DOCUMENTS: list[DemoDocument] = [
    DemoDocument(
        title="SARVEX Demo Knowledge: Radar Backscatter Fundamentals",
        topic="SAR_METHOD",
        text="""# Radar Backscatter Fundamentals

## What backscatter means
Synthetic aperture radar (SAR) measures the intensity and phase of microwave
energy returned from the surface. The normalized backscatter coefficient
sigma0 describes how much energy a surface returns per unit area. It depends on
surface roughness, dielectric properties (notably moisture), vegetation
structure, local incidence angle and wavelength.

## Decibel representation
Backscatter is commonly expressed in decibels: sigma0_dB = 10 log10(sigma0).
A difference of 1 dB is approximately a 26 percent change in linear power.
SARVEX stores backscatter in dB and records whether an input product was
already in dB or required conversion from linear power.

## Speckle
Coherent imaging produces multiplicative speckle. Multi-look processing and
spatial averaging reduce speckle variance at the cost of spatial resolution.
SARVEX reports spatial resolution alongside any smoothed result.

## Polarization
VV and HH are co-polarized channels; VH and HV are cross-polarized channels.
Cross-polarized returns are generally sensitive to volume scattering from
vegetation. Polarization channels must never be combined without stating which
channels were used and why.

## Interpretation limits
A backscatter decrease can result from flooding, smoothing of the surface,
vegetation removal, or a change in viewing geometry. A backscatter increase can
result from surface roughening, regrowth, or built surfaces. Backscatter alone
does not identify a cause.
""",
    ),
    DemoDocument(
        title="SARVEX Demo Knowledge: Interferometric Phase and Coherence",
        topic="INSAR_METHOD",
        text="""# Interferometric Phase and Coherence

## Phase difference
Interferometric SAR compares the phase of two acquisitions. The measured phase
difference contains contributions from surface displacement, topography,
atmosphere, orbit error and noise. After removing topographic and orbital
contributions, the remaining phase can be converted to line-of-sight
displacement.

## Phase to displacement
For a given radar wavelength lambda, line-of-sight displacement d_LOS is related
to interferometric phase phi by d_LOS = -(lambda / (4*pi)) * phi. One complete
2*pi phase cycle corresponds to half a wavelength of line-of-sight motion. The
sign convention must be stated with every result. SARVEX uses a negative sign
for motion toward the sensor and records this convention.

## Coherence
Interferometric coherence is a normalized correlation between the two complex
images, ranging from 0 to 1. Low coherence indicates decorrelation caused by
vegetation change, water, temporal change, thermal noise or processing issues.
Coherence is a quality indicator, not a direct measurement of change.

## Phase unwrapping
Wrapped phase is limited to (-pi, pi]. Unwrapping recovers a continuous phase
field. Unwrapping errors are spatially correlated and can bias displacement.
SARVEX consumes unwrapped products where provided and does not re-unwrap phase
in its baseline pipeline; deeper unwrapping belongs to the ISCE3 capability
boundary.

## Limitations
Line-of-sight measurements do not separate vertical and horizontal motion.
Atmospheric delay and orbital ramps can mimic deformation. Values are relative
to an arbitrary reference unless an absolute reference is established. A
detected displacement pattern is not a confirmed earthquake, subsidence or
landslide without independent evidence.
""",
    ),
    DemoDocument(
        title="SARVEX Demo Knowledge: NISAR Product Families",
        topic="NISAR_PRODUCT",
        text="""# NISAR Product Families (processing summary)

## Scope note
This note is a SARVEX processing summary, not an official NISAR product
specification. Exact product contents, calibration requirements and file
conventions must be taken from official NASA/ISRO NISAR documentation and the
NASA Alaska Satellite Facility or ISRO Bhoonidhi distribution channels.

## Product families used by SARVEX
RSLC: range-focused single-look complex data, suitable for interferometric and
offset processing after co-registration.
GSLC: geocoded single-look complex data with phase and amplitude.
GCOV: geocoded multi-looked backscatter products, typically used for
backscatter change, polarimetric channel analysis and temporal statistics.
RIFG: range-focused interferogram products containing phase (and typically
coherence) before geocoding.
RUNW: range-focused unwrapped interferogram products.
GUNW: geocoded unwrapped interferogram products, commonly used for displacement
analysis when phase, coherence and geolocation are supplied.
ROFF and GOFF: offset products in radar and geocoded geometry respectively,
used for offset tracking.

## Frequency bands
NISAR carries L-band and S-band SAR. L-band penetrates vegetation more deeply
and is often more coherent over vegetated terrain; S-band is more sensitive to
smaller-scale structure and can complement L-band observations. Wavelength must
be recorded for any phase-to-displacement conversion.

## Metadata that SARVEX requires
Provider, product identifier, product type, acquisition start/end time, orbit,
pass direction, track/frame where available, frequency band, polarization,
wavelength, CRS, bounding geometry, spatial resolution, processing baseline,
checksum, source URL and calibration status. Missing fields are recorded as
missing, never inferred silently.
""",
    ),
    DemoDocument(
        title="SARVEX Demo Knowledge: Transparent Change Detection Methods",
        topic="SAR_METHOD",
        text="""# Transparent Change Detection Methods

## Temporal median baseline
For multiple co-registered acquisitions, a per-pixel temporal median provides a
robust baseline that is insensitive to isolated outliers. The latest epoch is
compared against this baseline.

## Median absolute deviation
The median absolute deviation (MAD) measures spread robustly. With
sigma = 1.4826 * MAD, a robust z-score z = (x - median) / sigma indicates how
unusual an observation is relative to the baseline distribution.

## Thresholding
SARVEX combines a statistical threshold (default |z| >= 3.5) with a physical
magnitude threshold (default |delta sigma0| >= 1.0 dB). Both must be exceeded,
which reduces detections caused by tiny but statistically unusual fluctuations.

## Morphological cleanup
Binary opening removes isolated pixels; closing fills small holes. Connected
components below a minimum pixel count are removed. Every parameter is stored in
provenance.

## CUSUM and Theil-Sen
CUSUM detects a persistent shift in a time series. The Theil-Sen estimator
provides a robust linear trend with a confidence interval. These are reported as
statistics, not causal claims.

## Confidence and uncertainty
Detection confidence is a monotonic mapping of |z| around the threshold. It is
not the probability that a hazard occurred. Uncertainty in the AOI series is
reported from robust spread and sample size. All results carry units, method,
and provenance.
""",
    ),
    DemoDocument(
        title="SARVEX Demo Knowledge: Scientific Evidence Taxonomy",
        topic="INTERNAL_SARVEX",
        text="""# Scientific Evidence Taxonomy

## Stages
OBSERVED: measured directly in a SAR product.
DERIVED: computed deterministically from observations.
DETECTED: identified by an explicit algorithm.
CLASSIFIED: assigned to a candidate category by a stated method.
CONTEXTUALIZED: spatially correlated with independent context layers.
HYPOTHESIZED: a possible explanation requiring independent validation.
CONFIRMED: supported by authoritative external evidence.

## Rules
An algorithmic detection must not be described as an earthquake, flood or
landslide. A classification is a model-based category assignment, not a
confirmed cause. Confirmation requires independent evidence such as seismic
records, gauge measurements, official reports or field validation.

## Uncertainty language
Use calibrated language: observed, estimated, consistent with, possibly,
requires validation. Avoid words such as definitely, certainly, proves, or
caused by unless authoritative external evidence is cited.
""",
    ),
    DemoDocument(
        title="SARVEX Demo Knowledge: Dual-Polarization Observables",
        topic="POLARIMETRY",
        text="""# Dual-Polarization Observables

## Channels and ratios
Dual-pol SAR provides two channels, commonly VV and VH. The ratio VV/VH in dB
(vv_db - vh_db) summarizes the relative strength of co- and cross-polarized
returns. A decrease in VH relative to VV can accompany loss of vegetation
volume scattering; an increase can accompany regrowth or roughening.

## What dual-pol can and cannot support
Dual-pol features support hypotheses about vegetation structure and surface
roughness. They do not provide a full scattering decomposition. Full covariance
decompositions such as H/A/alpha or Freeman-Durden require calibrated
quad-polarimetric covariance data and are not approximated from two channels.

## Reporting
SARVEX reports candidate labels only, explicitly marked as hypotheses, and
requires independent validation before any category is promoted beyond
CLASSIFIED. Ratio changes are reported in dB with the acquisition dates and the
exact channel pair.
""",
    ),
]


def demo_document_texts() -> list[tuple[str, str, str]]:
    return [(doc.title, doc.topic, doc.text) for doc in DEMO_DOCUMENTS]
