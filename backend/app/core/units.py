"""Scientific unit registry and conversions.

Rules enforced here:
* Every persisted numeric quantity carries an explicit unit.
* Conversions are explicit and centralized; processors never guess units.
* Displacement conversion from interferometric phase uses the product
  wavelength and is documented, not assumed.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum


class UnitError(ValueError):
    """Raised for unit mismatches or unsupported conversions."""


class UnitCategory(str, Enum):
    BACKSCATTER = "backscatter"
    DISPLACEMENT = "displacement"
    PHASE = "phase"
    COHERENCE = "coherence"
    AREA = "area"
    LENGTH = "length"
    ANGLE = "angle"
    TIME = "time"
    RATIO = "ratio"
    DIMENSIONLESS = "dimensionless"
    VELOCITY = "velocity"


class Unit(str, Enum):
    DB = "dB"
    LINEAR_POWER = "linear_power"
    METER = "m"
    MILLIMETER = "mm"
    CENTIMETER = "cm"
    KILOMETER = "km"
    RADIAN = "rad"
    DEGREE = "deg"
    SQUARE_METER = "m2"
    SQUARE_KILOMETER = "km2"
    COHERENCE = "unitless[0,1]"
    RATIO = "ratio"
    PERCENT = "%"
    SECOND = "s"
    DAY = "day"
    MM_PER_YEAR = "mm/yr"
    M_PER_YEAR = "m/yr"
    UNITLESS = "unitless"


CATEGORY_OF: dict[Unit, UnitCategory] = {
    Unit.DB: UnitCategory.BACKSCATTER,
    Unit.LINEAR_POWER: UnitCategory.BACKSCATTER,
    Unit.METER: UnitCategory.LENGTH,
    Unit.MILLIMETER: UnitCategory.LENGTH,
    Unit.CENTIMETER: UnitCategory.LENGTH,
    Unit.KILOMETER: UnitCategory.LENGTH,
    Unit.SQUARE_METER: UnitCategory.AREA,
    Unit.SQUARE_KILOMETER: UnitCategory.AREA,
    Unit.RADIAN: UnitCategory.PHASE,
    Unit.DEGREE: UnitCategory.ANGLE,
    Unit.COHERENCE: UnitCategory.COHERENCE,
    Unit.RATIO: UnitCategory.RATIO,
    Unit.PERCENT: UnitCategory.RATIO,
    Unit.SECOND: UnitCategory.TIME,
    Unit.DAY: UnitCategory.TIME,
    Unit.MM_PER_YEAR: UnitCategory.VELOCITY,
    Unit.M_PER_YEAR: UnitCategory.VELOCITY,
    Unit.UNITLESS: UnitCategory.DIMENSIONLESS,
}

# Exact definitions are used so no precision is lost silently.
_LENGTH_TO_M = {
    Unit.METER: 1.0,
    Unit.MILLIMETER: 1e-3,
    Unit.CENTIMETER: 1e-2,
    Unit.KILOMETER: 1e3,
}
_LENGTH_CATEGORY = UnitCategory.LENGTH
_AREA_TO_M2 = {Unit.SQUARE_METER: 1.0, Unit.SQUARE_KILOMETER: 1e6}
_TIME_TO_S = {Unit.SECOND: 1.0, Unit.DAY: 86400.0}
_ANGLE_TO_RAD = {Unit.RADIAN: 1.0, Unit.DEGREE: math.pi / 180.0}
_VELOCITY_TO_MM_YR = {Unit.MM_PER_YEAR: 1.0, Unit.M_PER_YEAR: 1000.0}


def unit_category(unit: Unit) -> UnitCategory:
    return CATEGORY_OF[unit]


def to_canonical(value: float, unit: Unit) -> tuple[float, Unit]:
    """Convert to the canonical unit for the category."""
    if unit in _LENGTH_TO_M:
        return value * _LENGTH_TO_M[unit], Unit.METER
    if unit in _AREA_TO_M2:
        return value * _AREA_TO_M2[unit], Unit.SQUARE_METER
    if unit in _TIME_TO_S:
        return value * _TIME_TO_S[unit], Unit.SECOND
    if unit in _ANGLE_TO_RAD:
        return value * _ANGLE_TO_RAD[unit], Unit.RADIAN
    if unit in _VELOCITY_TO_MM_YR:
        return value * _VELOCITY_TO_MM_YR[unit], Unit.MM_PER_YEAR
    if unit == Unit.PERCENT:
        return value / 100.0, Unit.RATIO
    return value, unit


def convert(value: float, source: Unit, target: Unit) -> float:
    """Convert a value between compatible units."""
    if source == target:
        return value
    if unit_category(source) != unit_category(target):
        raise UnitError(f"Cannot convert {source.value} ({unit_category(source)}) to {target.value}")
    if source == Unit.DB or target == Unit.DB or source == Unit.LINEAR_POWER or target == Unit.LINEAR_POWER:
        # Power conversion. Mixing DB and LINEAR_POWER is allowed by design.
        if source in (Unit.DB, Unit.LINEAR_POWER) and target in (Unit.DB, Unit.LINEAR_POWER):
            if source == Unit.DB and target == Unit.LINEAR_POWER:
                return 10.0 ** (value / 10.0)
            if source == Unit.LINEAR_POWER and target == Unit.DB:
                if value <= 0:
                    return float("-inf")
                return 10.0 * math.log10(value)
            raise UnitError("Unsupported backscatter conversion")
    canonical, canon_unit = to_canonical(value, source)
    target_canonical, target_unit = to_canonical(1.0, target)
    if canon_unit != target_unit:
        raise UnitError(f"No canonical path between {source.value} and {target.value}")
    return canonical / target_canonical


def linear_power_to_db(value: float, floor: float = 1e-12) -> float:
    return 10.0 * math.log10(max(float(value), floor))


def db_to_linear_power(value_db: float) -> float:
    return 10.0 ** (float(value_db) / 10.0)


def coherence_phase_sigma(coherence: float, looks: float = 1.0) -> float:
    """Approximate single-look interferometric phase standard deviation [rad].

    Uses the standard high-coherence approximation
    sigma_phi ~= sqrt((1 - gamma^2) / (2 * gamma^2 * N)) (Hanssen, 2001).
    Values are clamped to the physically meaningful coherence range.
    """
    gamma = min(max(float(coherence), 1e-3), 0.9999)
    n = max(float(looks), 1.0)
    return math.sqrt(max((1.0 - gamma**2), 0.0) / (2.0 * gamma**2 * n))


def phase_to_los_displacement(phase_rad: float, wavelength_m: float) -> float:
    """Convert interferometric phase to line-of-sight displacement [m].

    d_los = -lambda / (4*pi) * phi. The sign follows the convention that
    positive phase corresponds to motion away from the sensor; the convention
    is recorded with every result.
    """
    if wavelength_m <= 0:
        raise UnitError("Wavelength must be positive for phase conversion")
    return -(wavelength_m / (4.0 * math.pi)) * float(phase_rad)


def phase_to_displacement_mm(phase_rad: float, wavelength_m: float) -> float:
    return phase_to_los_displacement(phase_rad, wavelength_m) * 1000.0


@dataclass(frozen=True)
class ScientificQuantity:
    """A numeric result that can never travel without unit + method metadata."""

    value: float
    unit: Unit
    method: str
    source: str
    uncertainty: float | None = None
    confidence: float | None = None
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.unit == Unit.COHERENCE and not (0.0 <= self.value <= 1.0):
            raise UnitError("Coherence must lie in [0, 1]")
        if self.uncertainty is not None and self.uncertainty < 0:
            raise UnitError("Uncertainty cannot be negative")
        if self.confidence is not None and not (0.0 <= self.confidence <= 1.0):
            raise UnitError("Confidence must lie in [0, 1]")

    def converted(self, target: Unit) -> "ScientificQuantity":
        return ScientificQuantity(
            value=convert(self.value, self.unit, target),
            unit=target,
            method=self.method,
            source=self.source,
            uncertainty=(convert(self.uncertainty, self.unit, target) if self.uncertainty is not None else None),
            confidence=self.confidence,
            metadata=dict(self.metadata),
        )

    def as_dict(self) -> dict:
        return {
            "value": self.value,
            "unit": self.unit.value,
            "uncertainty": self.uncertainty,
            "confidence": self.confidence,
            "method": self.method,
            "source": self.source,
            "metadata": dict(self.metadata),
        }
