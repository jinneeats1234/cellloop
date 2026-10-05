"""Single source of truth for the CellLoop experiment schema.

The ORM columns, the LLM extraction JSON schema, server-side validation, metadata
completeness scoring and the frontend review form are all generated from FIELD_SPECS.
Adding a field here propagates everywhere.
"""

import math
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Literal

FieldType = Literal["str", "float", "int", "date"]


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    group: str
    type: FieldType
    unit: str | None = None
    required: bool = False  # counts toward the "complete metadata" metric
    description: str = ""
    min: float | None = None
    max: float | None = None
    examples: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["examples"] = list(self.examples)
        return d


FIELD_SPECS: tuple[FieldSpec, ...] = (
    # Identification
    FieldSpec("cell_id", "Partner cell ID", "Identification", "str", required=True,
              description="Identifier the partner lab uses for this cell or button sample."),
    FieldSpec("lab_name", "Testing lab", "Identification", "str", required=True),
    FieldSpec("operator", "Operator", "Identification", "str"),
    FieldSpec("test_date", "Test date", "Identification", "date", required=True,
              description="Date the electrochemical test started (ISO 8601)."),
    # Cell architecture
    FieldSpec("support_alloy", "Metal support alloy", "Cell architecture", "str", required=True,
              examples=("Ferritic stainless 430L", "Crofer 22 APU", "ITM (Plansee)")),
    FieldSpec("anode_composition", "Anode composition", "Cell architecture", "str", required=True,
              examples=("Ni-YSZ 60:40 wt%", "Ni-GDC", "Ni-ScSZ")),
    FieldSpec("electrolyte_composition", "Electrolyte composition", "Cell architecture", "str", required=True,
              examples=("8YSZ", "10Sc1CeSZ", "GDC")),
    FieldSpec("cathode_composition", "Cathode composition", "Cell architecture", "str", required=True,
              examples=("LSCF", "LSCF-GDC", "PrOx", "LSC")),
    FieldSpec("anode_thickness_um", "Anode thickness", "Cell architecture", "float", "µm", True, min=1, max=500),
    FieldSpec("electrolyte_thickness_um", "Electrolyte thickness", "Cell architecture", "float", "µm", True, min=0.5, max=200),
    FieldSpec("cathode_thickness_um", "Cathode thickness", "Cell architecture", "float", "µm", True, min=1, max=200),
    FieldSpec("active_area_cm2", "Active area", "Cell architecture", "float", "cm²", True, min=0.05, max=1000),
    # Processing
    FieldSpec("sintering_temp_c", "Sintering temperature", "Processing", "float", "°C", True, min=600, max=1600),
    FieldSpec("sintering_time_h", "Sintering dwell time", "Processing", "float", "h", True, min=0.1, max=48),
    FieldSpec("sintering_atmosphere", "Sintering atmosphere", "Processing", "str", required=True,
              examples=("reducing (2% H2/Ar)", "vacuum", "air")),
    # Protective coating
    FieldSpec("coating_material", "Support coating", "Protective coating", "str", required=True,
              description="Protective coating on the steel support / interconnect side. Use 'none' if uncoated.",
              examples=("MnCo2O4 spinel", "CeO2", "none")),
    FieldSpec("coating_thickness_um", "Coating thickness", "Protective coating", "float", "µm", min=0, max=100),
    # Test conditions
    FieldSpec("operating_temp_c", "Operating temperature", "Test conditions", "float", "°C", True, min=400, max=1000),
    FieldSpec("fuel_composition", "Fuel", "Test conditions", "str", required=True,
              examples=("97% H2 / 3% H2O", "50% H2 / 50% N2")),
    FieldSpec("oxidant", "Oxidant", "Test conditions", "str", examples=("air", "O2")),
    # Results
    FieldSpec("asr_ohm_cm2", "Total ASR", "Results", "float", "Ω·cm²", True, min=0.005, max=50,
              description="Total area-specific resistance at the operating temperature (ohmic + polarization)."),
    FieldSpec("ohmic_asr_ohm_cm2", "Ohmic ASR", "Results", "float", "Ω·cm²", min=0, max=50),
    FieldSpec("polarization_asr_ohm_cm2", "Polarization ASR", "Results", "float", "Ω·cm²", min=0, max=50),
    FieldSpec("peak_power_density_w_cm2", "Peak power density", "Results", "float", "W/cm²", min=0, max=5),
    FieldSpec("ocv_v", "Open-circuit voltage", "Results", "float", "V", min=0, max=1.4),
    FieldSpec("degradation_pct_per_khr", "Degradation rate", "Results", "float", "%/kh", min=-10, max=100),
    FieldSpec("thermal_cycles", "Thermal cycles survived", "Results", "int", min=0, max=100000),
    FieldSpec("notes", "Notes", "Results", "str"),
)

FIELDS_BY_KEY = {f.key: f for f in FIELD_SPECS}
REQUIRED_KEYS = tuple(f.key for f in FIELD_SPECS if f.required)

# Continuous design variables the Bayesian optimizer searches over, with search bounds.
DESIGN_SPACE: dict[str, tuple[float, float]] = {
    "anode_thickness_um": (10.0, 60.0),
    "electrolyte_thickness_um": (2.0, 20.0),
    "cathode_thickness_um": (10.0, 50.0),
    "sintering_temp_c": (1000.0, 1350.0),
    "sintering_time_h": (0.5, 6.0),
    "coating_thickness_um": (0.0, 20.0),
}
OBJECTIVE_KEY = "asr_ohm_cm2"


# Any magnitude beyond this is a typo or an attack, never a measurement. Hard-rejected so it
# can't reach the database (integer overflow) or the JSON encoder (inf/NaN are not valid JSON).
ABSURD_MAGNITUDE = 1e9
MAX_TEXT_LEN = 5000


def coerce_value(spec: FieldSpec, raw: Any) -> tuple[Any, str | None]:
    """Coerce a raw (possibly string) value into the field's type.

    Returns (value, problem). If `value` is None and `problem` is set, the input is invalid
    and must be rejected. If both are set, the value is usable but implausible: it is kept
    (a scientist may know better) and flagged for confirmation.
    """
    if raw is None or (isinstance(raw, str) and raw.strip() in {"", "null", "None", "n/a", "N/A"}):
        return None, None
    if isinstance(raw, bool) or isinstance(raw, (dict, list)):
        return None, f"Expected a {spec.type}, got {type(raw).__name__}"
    if isinstance(raw, str) and "\x00" in raw:
        return None, "Contains an invalid character"
    try:
        if spec.type == "str":
            text = str(raw).strip()
            if len(text) > MAX_TEXT_LEN:
                return None, f"Keep this under {MAX_TEXT_LEN} characters"
            return text, None
        if spec.type == "date":
            if isinstance(raw, date):
                return raw, None
            return date.fromisoformat(str(raw).strip()[:10]), None
        number = float(str(raw).replace(",", "").strip()) if isinstance(raw, str) else float(raw)
    except (TypeError, ValueError, OverflowError):
        return None, f"Could not parse '{str(raw)[:40]}' as {spec.type}"
    if not math.isfinite(number):
        return None, "Must be a finite number"
    if abs(number) > ABSURD_MAGNITUDE:
        return None, f"{number:g} is far outside any plausible value"
    value: float | int = int(round(number)) if spec.type == "int" else number
    if spec.min is not None and value < spec.min or spec.max is not None and value > spec.max:
        unit = f" {spec.unit}" if spec.unit else ""
        return value, f"{value}{unit} is outside the plausible range [{spec.min}, {spec.max}]"
    return value, None


def completeness(record: dict[str, Any]) -> tuple[float, list[str]]:
    """Fraction of required metadata fields present, plus the list of missing keys."""
    missing = [k for k in REQUIRED_KEYS if record.get(k) in (None, "")]
    return 1 - len(missing) / len(REQUIRED_KEYS), missing


def extraction_json_schema() -> dict[str, Any]:
    """JSON schema for Claude structured output: a list of experiments, each field
    carrying a value, a confidence and a verbatim evidence quote from the source."""
    type_map = {"str": "string", "float": "number", "int": "integer", "date": "string"}
    field_props: dict[str, Any] = {}
    for f in FIELD_SPECS:
        field_props[f.key] = {
            "type": "object",
            "properties": {
                "value": {"anyOf": [{"type": type_map[f.type]}, {"type": "null"}]},
                "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                "evidence": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            },
            "required": ["value", "confidence", "evidence"],
            "additionalProperties": False,
        }
    return {
        "type": "object",
        "properties": {
            "experiments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": field_props,
                    "required": list(field_props),
                    "additionalProperties": False,
                },
            },
            "extraction_notes": {"type": "string"},
        },
        "required": ["experiments", "extraction_notes"],
        "additionalProperties": False,
    }


def field_guide() -> str:
    """Compact field reference for the extraction prompt."""
    lines = []
    for f in FIELD_SPECS:
        unit = f" [{f.unit}]" if f.unit else ""
        ex = f" e.g. {', '.join(f.examples)}" if f.examples else ""
        desc = f" — {f.description}" if f.description else ""
        lines.append(f"- {f.key} ({f.type}{unit}): {f.label}{desc}{ex}")
    return "\n".join(lines)
