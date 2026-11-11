"""Scientific NLP intent parser for SARVEX queries.

Extracts structured analysis intent from natural language. Uses rule-based
parsing first, with an optional LLM fallback for ambiguous queries.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

ANALYSIS_KEYWORDS = {
    "deformation": "deformation",
    "subsidence": "deformation",
    "displacement": "deformation",
    "insar": "deformation",
    "flood": "change_detection",
    "inundation": "change_detection",
    "water": "change_detection",
    "backscatter": "backscatter",
    "change": "change_detection",
    "polarimetric": "polarimetric",
    "polarization": "polarimetric",
    "offset": "offsets",
    "shift": "offsets",
    "timeseries": "timeseries",
    "trend": "timeseries",
    "time series": "timeseries",
}

CONTEXT_KEYWORDS = {
    "infrastructure": ["infrastructure"],
    "road": ["roads"],
    "building": ["buildings"],
    "water": ["water"],
    "river": ["water"],
    "population": ["population"],
    "exposure": ["infrastructure", "population"],
}

FREQUENCY_KEYWORDS = {
    "l-band": "L", "l band": "L", "lband": "L",
    "s-band": "S", "s band": "S", "sband": "S",
}


@dataclass
class AnalysisIntent:
    intent: str = "analysis"
    aoi: str | None = None
    date_start: str | None = None
    date_end: str | None = None
    analysis_type: str | None = None
    product_preference: list[str] = field(default_factory=list)
    frequency: str | None = None
    polarization: str | None = None
    context_layers: list[str] = field(default_factory=list)
    output_type: str = "intelligence"
    constraints: dict[str, Any] = field(default_factory=dict)
    raw_query: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class NLPIntentParser:
    def parse(self, query: str) -> AnalysisIntent:
        q = query.strip()
        low = q.lower()
        intent = AnalysisIntent(raw_query=q)

        # analysis type
        for kw, atype in ANALYSIS_KEYWORDS.items():
            if kw in low:
                intent.analysis_type = atype
                break

        # frequency
        for kw, band in FREQUENCY_KEYWORDS.items():
            if kw in low:
                intent.frequency = band
                break

        # polarization
        for pol in ("vv", "vh", "hh", "hv", "vv+vh", "dual"):
            if pol in low:
                intent.polarization = pol.upper()
                break

        # context layers
        ctx = set()
        for kw, layers in CONTEXT_KEYWORDS.items():
            if kw in low:
                ctx.update(layers)
        intent.context_layers = sorted(ctx)

        # dates: month names
        months_found = []
        for name, num in MONTHS.items():
            if re.search(r"\b" + re.escape(name) + r"\b", low):
                months_found.append((name, num))
        if months_found:
            # use first and last found month as range within current year
            nums = sorted({m[1] for m in months_found})
            year = datetime.now().year
            intent.date_start = f"{year:04d}-{nums[0]:02d}-01"
            if len(nums) > 1:
                # end of last month (approx)
                last = nums[-1]
                intent.date_end = f"{year:04d}-{last:02d}-28"
            else:
                intent.date_end = intent.date_start

        # between X and Y
        m = re.search(r"between\s+(\w+)\s+and\s+(\w+)", low)
        if m:
            a = MONTHS.get(m.group(1).lower())
            b = MONTHS.get(m.group(2).lower())
            if a and b:
                year = datetime.now().year
                intent.date_start = f"{year:04d}-{a:02d}-01"
                intent.date_end = f"{year:04d}-{b:02d}-28"

        # AOI: capture "around X", "near X", "in X", "over X"
        for pattern in (r"around\s+([A-Za-z][A-Za-z\s]{2,30})", r"near\s+([A-Za-z][A-Za-z\s]{2,30})", r"over\s+([A-Za-z][A-Za-z\s]{2,30})", r"in\s+([A-Za-z][A-Za-z\s]{2,30})"):
            m = re.search(pattern, q)
            if m:
                candidate = m.group(1).strip().rstrip(".,?!")
                # trim trailing keywords
                for stop in ("between", "from", "with", "and", "show", "tell"):
                    if " " + stop in " " + candidate.lower():
                        candidate = candidate[: candidate.lower().index(" " + stop)].strip()
                if candidate and len(candidate) < 40:
                    intent.aoi = candidate
                    break

        # product preference
        for pt in ("RSLC", "GSLC", "GCOV", "GUNW", "RUNW", "RIFG", "ROFF", "GOFF"):
            if pt in q.upper():
                intent.product_preference.append(pt)

        # persistence
        if "persistent" in low or "persistent" in low:
            intent.constraints["persistence"] = "persistent"
        if "recurring" in low:
            intent.constraints["persistence"] = "recurring"

        # output type
        if "report" in low:
            intent.output_type = "report"
        if "risk" in low or "exposure" in low:
            intent.output_type = "intelligence"

        if intent.analysis_type is None:
            intent.analysis_type = "change_detection"

        return intent


def parse_intent(query: str) -> AnalysisIntent:
    return NLPIntentParser().parse(query)
