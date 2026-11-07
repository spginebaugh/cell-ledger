"""Build hand-curated SampleSheet + Contrast fixtures for the example datasets.

Rules below were written by reading each series' SOFT metadata. They are the
ground truth the harmonizer is later scored against, so every rule cites the
verbatim GEO string it keys on and nothing is inferred from sample order.

    uv run python scripts/fetch_geo_examples.py      # first
    uv run python scripts/build_example_samplesheets.py
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from cell_ledger.geo import GeoSample, read_soft
from cell_ledger.samplesheet import Assay, Contrast, ContrastStatus, Group, Sample, SampleSheet

DATA = Path(__file__).parents[1] / "data" / "geo"
FIXTURES = Path(__file__).parents[1] / "packages" / "core" / "tests" / "fixtures" / "geo_examples"

Getter = str | Callable[[GeoSample, dict[str, str]], str | None]


@dataclass
class Rules:
    """How to label one series.

    ``group_from``: characteristics key (or ``"source_name"``) whose value is looked
    up in ``groups``. ``fields``: Sample field -> characteristics key or callable.
    """

    group_from: str
    groups: dict[str, Group]
    contrast: str
    case_label: str
    control_label: str
    fields: dict[str, Getter] = field(default_factory=dict)
    blocking: str | None = None
    restricted_to: dict[str, str] = field(default_factory=dict)
    rationale: str = ""
    constant: dict[str, str] = field(default_factory=dict)
    markers_up: list[str] = field(default_factory=list)
    markers_down: list[str] = field(default_factory=list)


def _donor_from_source(s: GeoSample, _: dict[str, str]) -> str | None:
    m = re.match(r"(Donor \d+)", s.source_name)
    return m.group(1) if m else None


def _patient_from_title_number(s: GeoSample, _: dict[str, str]) -> str | None:
    """GSE140343 titles 'RNA-seq_LADC17' / 'RNA-seq_normal_lung17' share the patient number."""
    m = re.search(r"(\d+)$", s.title)
    return f"patient {m.group(1)}" if m else None


RULES: dict[str, Rules] = {
    "GSE114286": Rules(
        group_from="participant condition",
        groups={"psoriasis vulgaris patient": Group.CASE, "healthy\xa0volunteer": Group.CONTROL},
        contrast="psoriasis_vs_healthy",
        case_label="psoriasis vulgaris lesional skin",
        control_label="healthy skin",
        fields={"sex": "gender", "age": "age (years)", "tissue": "tissue"},
        rationale="Healthy value contains a non-breaking space in GEO; kept verbatim.",
        markers_up=["S100A7", "S100A8", "S100A9", "DEFB4A", "KRT16", "PI3", "IL36G", "SERPINB4"],
    ),
    "GSE67785": Rules(
        group_from="group",
        groups={"PP": Group.CASE, "PN": Group.CONTROL},
        contrast="lesional_vs_nonlesional",
        case_label="psoriasis lesional (PP)",
        control_label="psoriasis uninvolved (PN)",
        fields={"donor": "patient", "sex": "gender"},
        blocking="donor",
        constant={"tissue": "skin"},
        rationale="Paired: PP and PN from the same 14 patients.",
        markers_up=["S100A7", "S100A8", "S100A9", "DEFB4A", "KRT16", "PI3", "IL36G", "SERPINB4"],
    ),
    "GSE185492": Rules(
        group_from="diagnosis",
        groups={"idiopathic pulmonary fibrosis (IPF)": Group.CASE, "control donor": Group.CONTROL},
        contrast="ipf_vs_control",
        case_label="IPF lung fibroblasts",
        control_label="control lung fibroblasts",
        fields={"tissue": "tissue", "cell_type": "cell type"},
        rationale="Apex/base region sub-factor in titles ignored for v1.",
    ),
    "GSE79544": Rules(
        group_from="disease",
        groups={"Idiopathic pulmonary fibrosis": Group.CASE, "Control": Group.CONTROL},
        contrast="ipf_vs_control",
        case_label="IPF BAL macrophages",
        control_label="control BAL macrophages",
        fields={"sex": "Sex", "age": "age", "tissue": "tissue"},
        rationale="Unbalanced (16 vs 7); shallow libraries.",
    ),
    "GSE135631": Rules(
        group_from="tissue",
        groups={"tumor": Group.CASE, "Adjacent normal": Group.CONTROL},
        contrast="tumor_vs_adjacent_normal",
        case_label="HCC tumor",
        control_label="adjacent normal liver",
        fields={"donor": "individual"},
        blocking="donor",
        constant={"tissue": "liver"},
        rationale="Paired tumor/adjacent from 15 patients.",
    ),
    "GSE140343": Rules(
        group_from="source_name",
        groups={"LUAD": Group.CASE, "Clinical normal lung tissue": Group.CONTROL},
        contrast="tumor_vs_adjacent_normal",
        case_label="lung adenocarcinoma tumor",
        control_label="adjacent normal lung",
        fields={"age": "age", "tissue": "tissue", "donor": _patient_from_title_number},
        blocking="donor",
        rationale=(
            "Tumor samples lack a 'disease state' characteristic; label is from source_name. "
            "Paired tumor/adjacent per patient, patient number taken from the sample title."
        ),
    ),
    "GSE232753": Rules(
        group_from="disease state",
        groups={"sepsis": Group.CASE, "none": Group.CONTROL},
        contrast="sepsis_vs_healthy",
        case_label="sepsis whole blood",
        control_label="healthy whole blood",
        fields={"tissue": "tissue", "time_point": "time"},
        markers_up=["MMP8", "CD177", "OLFM4", "ARG1", "LCN2", "HP", "RETN", "MMP9"],
    ),
    "GSE233547": Rules(
        group_from="treatment",
        groups={"hypoxia (1% oxygen)": Group.CASE, "normoxia (21% oxygen)": Group.CONTROL},
        contrast="hypoxia_vs_normoxia",
        case_label="hypoxia 1% O2",
        control_label="normoxia 21% O2",
        fields={
            "treatment": "treatment",
            "time_point": "time",
            "sex": "Sex",
            "age": "age (years)",
            "donor": "lot number",
            "cell_type": "cell type",
        },
        blocking="donor",
        restricted_to={"time_point": "48 hours"},
        rationale=(
            "48 h only (two time points per donor would be pseudo-replication); "
            "5 of 6 donors have both arms quantified. Sex is a second factor ignored in v1."
        ),
        markers_up=["VEGFA", "CA9", "PGK1", "SLC2A1", "BNIP3", "ADM", "LDHA", "PDK1", "NDRG1"],
    ),
    "GSE111414": Rules(
        group_from="response",
        groups={
            "responder; partial response (PR)": Group.CASE,
            "nonresponder; progressive disease (PD)": Group.CONTROL,
        },
        contrast="responder_vs_nonresponder",
        case_label="PD-1 responder CD8 T cells",
        control_label="PD-1 nonresponder CD8 T cells",
        fields={
            "donor": "subject id",
            "sex": "Sex",
            "age": "age",
            "time_point": "timepoint",
            "cell_type": "cell subtype",
            "genotype": "kir3ds1/l1 genotype",
        },
        restricted_to={"time_point": "N1"},
        rationale="Pre-treatment (N1) samples only; 5 vs 5 is the minimum we accept.",
    ),
    "GSE82227": Rules(
        group_from="stimulation",
        groups={
            "interferon gamma": Group.CASE,
            "media alone": Group.CONTROL,
            "TLR2/1 ligand": Group.OTHER,
        },
        contrast="ifng_vs_media_24h",
        case_label="IFN-gamma 24 h",
        control_label="media alone 24 h",
        fields={
            "treatment": "stimulation",
            "time_point": "stimulation length",
            "cell_type": "cell type",
            "donor": _donor_from_source,
        },
        blocking="donor",
        restricted_to={"time_point": "24 hours"},
        rationale="Expect CXCL9/10/11, IDO1, GBP1 up. Donors paired across arms.",
        markers_up=["CXCL9", "CXCL10", "CXCL11", "IDO1", "GBP1", "GBP5", "STAT1", "IRF1", "CIITA"],
    ),
}


def _get(s: GeoSample, chars: dict[str, str], getter: Getter) -> str | None:
    if callable(getter):
        return getter(s, chars)
    return chars.get(getter)


def build(gse: str, rules: Rules) -> tuple[SampleSheet, Contrast]:
    series = read_soft(DATA / gse / f"{gse}_family.soft.gz")
    samples: list[Sample] = []
    for s in series.samples:
        chars = s.characteristics_dict()
        if rules.group_from == "source_name":
            key_value, evidence = s.source_name, s.source_name
        else:
            key_value = chars.get(rules.group_from, "")
            evidence = f"{rules.group_from}: {key_value}"
        group = rules.groups.get(key_value, Group.UNKNOWN)
        fields = {k: _get(s, chars, g) for k, g in rules.fields.items()}
        fields.update(rules.constant)
        samples.append(
            Sample(
                gsm=s.gsm,
                title=s.title,
                source_name=s.source_name or None,
                organism=s.organism or None,
                group=group,
                condition=key_value if group in (Group.CASE, Group.CONTROL, Group.OTHER) else None,
                evidence=[evidence] if group is not Group.UNKNOWN else [],
                confidence=1.0 if group is not Group.UNKNOWN else None,
                raw=chars,
                raw_lines=list(s.characteristics),
                **fields,
            )
        )
    sheet = SampleSheet(gse=gse, assay=Assay.BULK, title=series.title, samples=samples)

    def in_contrast(x: Sample) -> bool:
        return all(getattr(x, k) == v for k, v in rules.restricted_to.items())

    contrast = Contrast(
        gse=gse,
        name=rules.contrast,
        case_label=rules.case_label,
        control_label=rules.control_label,
        case_gsms=[x.gsm for x in samples if x.group is Group.CASE and in_contrast(x)],
        control_gsms=[x.gsm for x in samples if x.group is Group.CONTROL and in_contrast(x)],
        blocking=rules.blocking,
        restricted_to=rules.restricted_to,
        confidence=1.0,
        status=ContrastStatus.CONFIRMED,
        rationale=rules.rationale,
    )
    return sheet, contrast


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for gse, rules in RULES.items():
        sheet, contrast = build(gse, rules)
        problems = contrast.problems(sheet)
        counts = sheet.group_counts()
        groups = ", ".join(f"{k}:{v}" for k, v in counts.items())
        print(
            f"{gse}: {contrast.name} case={len(contrast.case_gsms)} "
            f"control={len(contrast.control_gsms)} groups={{{groups}}} {problems or 'OK'}"
        )
        doc = {
            "samplesheet": sheet.model_dump(mode="json"),
            "contrasts": [contrast.model_dump(mode="json")],
            "markers": [
                *({"symbol": g, "direction": "up"} for g in rules.markers_up),
                *({"symbol": g, "direction": "down"} for g in rules.markers_down),
            ],
        }
        (FIXTURES / f"{gse}.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
