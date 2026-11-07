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
GroupKey = str | Callable[[GeoSample, dict[str, str]], tuple[str, str]]
Predicate = Callable[[GeoSample, dict[str, str]], bool]


@dataclass
class Rules:
    """How to label one series.

    ``group_from``: characteristics key (or ``"source_name"``) whose value is looked
    up in ``groups``, or a callable returning ``(key, verbatim evidence)``.
    ``fields``: Sample field -> characteristics key or callable. ``exclude``: samples
    for which it is true are left out of the sheet entirely (other assays, other
    diseases, treated arms); ``query_sets`` names the multi-dataset sets this
    series belongs to.
    """

    group_from: GroupKey
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
    exclude: Predicate | None = None
    query_sets: list[str] = field(default_factory=list)


def _donor_from_source(s: GeoSample, _: dict[str, str]) -> str | None:
    m = re.match(r"(Donor \d+)", s.source_name)
    return m.group(1) if m else None


def _patient_from_title_number(s: GeoSample, _: dict[str, str]) -> str | None:
    """GSE140343 titles 'RNA-seq_LADC17' / 'RNA-seq_normal_lung17' share the patient number."""
    m = re.search(r"(\d+)$", s.title)
    return f"patient {m.group(1)}" if m else None


def _title_re(pattern: str, prefix: str = "") -> Getter:
    """Donor id from the first group of ``pattern`` applied to the sample title."""

    def get(s: GeoSample, _: dict[str, str]) -> str | None:
        m = re.search(pattern, s.title)
        return f"{prefix}{m.group(1)}" if m else None

    return get


def _title_group(mapping: dict[str, str]) -> GroupKey:
    """Group key from a title prefix; the whole title is the verbatim evidence."""

    def key(s: GeoSample, _: dict[str, str]) -> tuple[str, str]:
        for prefix, label in mapping.items():
            if s.title.startswith(prefix):
                return label, s.title
        return "", s.title

    return key


def _char_is(key: str, *values: str) -> Predicate:
    return lambda _s, c: c.get(key) in values


def _char_not(key: str, *values: str) -> Predicate:
    return lambda _s, c: c.get(key) not in values


HCC_UP = ["GPC3", "AFP", "SPP1", "MDK", "PEG10"]
HCC_DOWN = ["CLEC4G", "CLEC1B", "FCN3", "CRHBP", "CYP1A2"]
PSO_UP = ["S100A7", "S100A8", "S100A9", "DEFB4A", "KRT16", "PI3", "IL36G", "SERPINB4"]
HCC_SET = ["hcc_tumor_vs_adjacent"]
PSO_SET = ["psoriasis_lesional_vs_control"]
PSO_STRATA = {
    "psoriasis_vs_healthy": "lesional_vs_healthy",
    "lesional_vs_healthy": "lesional_vs_healthy",
    "lesional_vs_nonlesional": "lesional_vs_nonlesional",
}


RULES: dict[str, Rules] = {
    "GSE114286": Rules(
        group_from="participant condition",
        groups={"psoriasis vulgaris patient": Group.CASE, "healthy\xa0volunteer": Group.CONTROL},
        contrast="psoriasis_vs_healthy",
        case_label="psoriasis vulgaris lesional skin",
        control_label="healthy skin",
        fields={"sex": "gender", "age": "age (years)", "tissue": "tissue"},
        rationale="Healthy value contains a non-breaking space in GEO; kept verbatim.",
        markers_up=PSO_UP,
        query_sets=PSO_SET,
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
        markers_up=PSO_UP,
        query_sets=PSO_SET,
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
        markers_up=HCC_UP,
        markers_down=HCC_DOWN,
        query_sets=HCC_SET,
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


def _hcc(**kw: object) -> Rules:
    base: dict[str, object] = dict(
        contrast="tumor_vs_adjacent_normal",
        case_label="HCC tumor",
        control_label="adjacent non-tumor liver",
        markers_up=HCC_UP,
        markers_down=HCC_DOWN,
        query_sets=HCC_SET,
    )
    base.update(kw)
    return Rules(**base)  # type: ignore[arg-type]


RULES.update(
    {
        "GSE77314": _hcc(
            group_from="diagnosis",
            groups={"Tumor": Group.CASE, "Normal": Group.CONTROL},
            fields={"tissue": "tissue", "donor": _title_re(r"^(Patient \d+)")},
            blocking="donor",
            rationale="50 pairs; patient number in the title.",
        ),
        "GSE124535": _hcc(
            group_from="tissue",
            groups={"HCC": Group.CASE, "non-tumor": Group.CONTROL},
            fields={"donor": _title_re(r"^(L\d+)[PT]$")},
            blocking="donor",
            constant={"tissue": "liver"},
            rationale="35 early-stage pairs; L001P (peritumoral) / L001T share the patient code.",
        ),
        "GSE144269": _hcc(
            group_from="tumor/non-tumor",
            groups={"tumor": Group.CASE, "non-tumor": Group.CONTROL},
            fields={"donor": _title_re(r"^(pat \d+)")},
            blocking="donor",
            constant={"tissue": "liver"},
            rationale="70 pairs, Mongolian cohort.",
        ),
        "GSE202069": _hcc(
            group_from="tissue",
            groups={"Tumor": Group.CASE, "Nontumor": Group.CONTROL},
            fields={"treatment": "treatment"},
            constant={"tissue": "liver"},
            rationale=(
                "Unpaired as deposited (no patient id). 17 of 41 tumors are post anti-PD-1 "
                "(treatment: PD1); kept in v1, a sub-factor the comparison can see."
            ),
        ),
        "GSE169289": _hcc(
            group_from="tissue",
            groups={"tumor": Group.CASE, "Adjacent tissue": Group.CONTROL},
            fields={"donor": _title_re(r"^RNA_(P\d+[PR]?)[NT]$")},
            blocking="donor",
            constant={"tissue": "liver"},
            rationale=(
                "17 pairs: RNA_P1N / RNA_P1T for patients 1-9; patients 10-13 contribute a "
                "primary (P10PN / P10PT) and a recurrent (P10RN / P10RT) pair, blocked separately."
            ),
        ),
        "GSE104310": _hcc(
            group_from="tissue",
            groups={"tumor": Group.CASE, "non-tumor": Group.CONTROL},
            fields={"donor": "individual"},
            blocking="donor",
            constant={"tissue": "liver"},
            rationale="12 tumors, 8 paired non-tumors; HBV and cirrhosis covariates in raw.",
        ),
        "GSE202853": _hcc(
            group_from="tissue",
            groups={"Hepatocellular carcinoma": Group.CASE, "normal liver": Group.CONTROL},
            fields={"sex": "gender", "donor": _title_re(r"^(HCC_\d+)_[NT]$")},
            blocking="donor",
            constant={"tissue": "liver"},
            rationale="10 pairs; SubSeries [I] of a SuperSeries, so check GSM overlap.",
        ),
        "GSE81550": _hcc(
            group_from="tissue type",
            groups={
                "hepatocellular carcinoma (HCC)": Group.CASE,
                "adjacent non-tumor tissue": Group.CONTROL,
            },
            fields={"donor": _title_re(r"_(p\d+)\s")},
            blocking="donor",
            constant={"tissue": "liver"},
            rationale="3 pairs: the minimum group size.",
        ),
        "GSE216613": _hcc(
            group_from="tissue",
            groups={
                "hepatocellular carcinoma": Group.CASE,
                "normal adjacent liver tissue": Group.CONTROL,
            },
            fields={"donor": _title_re(r"^[NP](\d)$", prefix="patient ")},
            blocking="donor",
            constant={"tissue": "liver"},
            rationale=(
                "3 pairs. Titles N1-3 are the tumors and P1-3 the normals; the tissue field is "
                "explicit and wins over the title letter."
            ),
        ),
        "GSE154211": _hcc(
            group_from="section",
            groups={"Tumor": Group.CASE, "Non-tumor": Group.CONTROL},
            fields={"tissue": "tissue", "donor": _title_re(r"^(\d+)[NT]$", prefix="patient ")},
            blocking="donor",
            rationale="5 pairs; etiology (HCV vs NBNC) is a sub-factor kept in raw.",
        ),
        "GSE77509": _hcc(
            group_from="tissue",
            groups={
                "primary tumor": Group.CASE,
                "adjacent normal": Group.CONTROL,
                "Portal vein tumor thrombosis (PVTT)": Group.OTHER,
            },
            fields={"donor": "patient id", "sex": "gender", "age": "age"},
            blocking="donor",
            constant={"tissue": "liver"},
            rationale="20 patients with adjacent / primary / PVTT; PVTT is a third arm, left out.",
        ),
        "GSE105130": _hcc(
            group_from="tissue",
            groups={"tumor": Group.CASE, "adjacent non-tumour": Group.CONTROL},
            fields={"donor": _title_re(r"^(P\d+)_")},
            blocking="donor",
            constant={"tissue": "liver"},
            rationale="25 patients; two contribute a second adjacent sample, summed per patient.",
        ),
        "GSE214846": _hcc(
            group_from="tissue",
            groups={
                "hepatocellular carcinoma": Group.CASE,
                "paracancerous normal tissues": Group.CONTROL,
            },
            fields={"donor": _title_re(r"^(sample\d+)_")},
            blocking="donor",
            constant={"tissue": "liver"},
            rationale="65 pairs; sampleN_HCC_tissue / sampleN_adjacent_non_HCC_tissue.",
        ),
        "GSE138485": _hcc(
            group_from=_title_group({"Non Tumor": "Non Tumor", "Tumor": "Tumor"}),
            groups={"Tumor": Group.CASE, "Non Tumor": Group.CONTROL},
            fields={"sex": "Sex", "age": "age"},
            constant={"tissue": "liver"},
            rationale=(
                "No tissue characteristic: the label is the title prefix ('Tumor T_A_004' vs "
                "'Non Tumor NT_JJ_017'), cited verbatim. Pairs cannot be recovered from the ids."
            ),
        ),
        "GSE146719": _hcc(
            group_from="tissue type",
            groups={"tumor tissue": Group.CASE, "paird non-tumor tissue": Group.CONTROL},
            fields={"donor": lambda s, _c: s.source_name.rstrip("TN") or None},
            blocking="donor",
            constant={"tissue": "liver"},
            exclude=lambda s, _c: s.library_strategy != "RNA-Seq",
            rationale="3 pairs of RNA-seq; the 6 miRNA-seq GSMs are another assay, excluded.",
        ),
        "GSE87410": _hcc(
            group_from="phenotype",
            groups={"cancer": Group.CASE, "paracancer": Group.CONTROL},
            fields={"tissue": "tissue", "donor": _title_re(r"^HCC_(G\d+)_[NT]$")},
            blocking="donor",
            restricted_to={"tissue": "liver"},
            exclude=_char_not("tissue", "liver"),
            rationale=(
                "Pan-cancer series: only the 6 liver pairs answer this question, and NCBI "
                "quantified 8 of those 12 GSMs (3 complete pairs)."
            ),
        ),
    }
)


def _pso(**kw: object) -> Rules:
    base: dict[str, object] = dict(markers_up=PSO_UP, query_sets=PSO_SET)
    base.update(kw)
    return Rules(**base)  # type: ignore[arg-type]


RULES.update(
    {
        "GSE54456": _pso(
            group_from="tissue type",
            groups={"lesional psoriatic skin": Group.CASE, "normal skin": Group.CONTROL},
            contrast="lesional_vs_healthy",
            case_label="psoriasis lesional skin",
            control_label="healthy skin",
            constant={"tissue": "skin"},
            rationale="92 lesional vs 82 normal; the large case-control reference set.",
        ),
        "GSE121212": _pso(
            group_from="skin type",
            groups={
                "lesional": Group.CASE,
                "healthy": Group.CONTROL,
                "non-lesional": Group.OTHER,
                "chronic_lesion": Group.OTHER,
            },
            contrast="lesional_vs_healthy",
            case_label="psoriasis lesional skin",
            control_label="healthy skin",
            fields={"donor": _title_re(r"^((?:PSO|CTRL|AD)_\d+)")},
            constant={"tissue": "skin"},
            exclude=_char_is("patient's condition", "AD"),
            rationale="Atopic dermatitis arm excluded; PSO non-lesional kept as 'other'.",
        ),
        "GSE154200": _pso(
            group_from="source_name",
            groups={"lesional skin": Group.CASE, "non-lesional skin": Group.CONTROL},
            contrast="lesional_vs_nonlesional",
            case_label="psoriasis lesional skin",
            control_label="psoriasis non-lesional skin",
            fields={"donor": "patient id", "sex": "gender", "age": "age", "batch": "batch id"},
            blocking="donor",
            constant={"tissue": "skin"},
            exclude=_char_not("diagnosis", "psoriasis"),
            rationale="Eczema arms excluded; paired by patient id; 7 sequencing batches.",
        ),
        "GSE171012": _pso(
            group_from="clinical status",
            groups={
                "Psoriasis_PreTreatment": Group.CASE,
                "Healthy": Group.CONTROL,
                "Psoriasis_SecukinumabTreatmentWeek2": Group.OTHER,
                "Psoriasis_SecukinumabTreatmentWeek4": Group.OTHER,
                "Psoriasis_SecukinumabTreatmentWeek12": Group.OTHER,
            },
            contrast="lesional_vs_healthy",
            case_label="psoriasis lesional skin, pre-treatment",
            control_label="healthy skin",
            fields={"donor": "subject id", "batch": "sequencing batch", "cell_type": "cell type"},
            constant={"tissue": "skin"},
            exclude=_char_not("cell type", "bulk"),
            rationale="Bulk skin only (sorted T cells excluded); on-treatment samples are 'other'.",
        ),
        "GSE74697": _pso(
            group_from="tissue type",
            groups={
                "lesional skin from psoriasis patient": Group.CASE,
                "normal skin": Group.CONTROL,
            },
            contrast="lesional_vs_healthy",
            case_label="psoriasis lesional skin, pre-treatment",
            control_label="healthy skin",
            fields={"time_point": "time point"},
            constant={"tissue": "skin"},
            exclude=_char_is("time point", "after 1 month of adalimumab treatment"),
            rationale="Post-adalimumab biopsies excluded.",
        ),
        "GSE186063": _pso(
            group_from="source_name",
            groups={"lesion": Group.CASE, "non-lesion": Group.CONTROL, "normal skin": Group.OTHER},
            contrast="lesional_vs_nonlesional",
            case_label="psoriasis / PsA lesional skin",
            control_label="psoriasis / PsA non-lesional skin",
            fields={"sex": "Sex", "age": "age"},
            constant={"tissue": "skin"},
            rationale="PsO and PsA pooled; AS 'normal skin' kept as 'other'. No patient id.",
        ),
        "GSE47944": _pso(
            group_from="tissue",
            groups={"Lesion": Group.CASE, "Nonlesion": Group.CONTROL, "Healthy": Group.OTHER},
            contrast="lesional_vs_nonlesional",
            case_label="psoriasis lesional skin, untreated explant",
            control_label="psoriasis non-lesional skin, untreated explant",
            fields={"donor": "patient", "sex": "gender", "age": "age", "treatment": "treatment"},
            blocking="donor",
            constant={"tissue": "skin"},
            exclude=_char_not("treatment", "Untreated"),
            rationale="Cultured explants, untreated arm only; healthy donors are 'other'.",
        ),
        "GSE178197": _pso(
            group_from="tissue",
            groups={
                "Lesional Skin": Group.CASE,
                "Uninvolved Skin": Group.CONTROL,
                "Normal": Group.OTHER,
            },
            contrast="lesional_vs_nonlesional",
            case_label="psoriasis lesional skin biopsy",
            control_label="psoriasis uninvolved skin biopsy",
            fields={"donor": "patient id"},
            blocking="donor",
            constant={"tissue": "skin"},
            exclude=_char_not("protocol", "Biopsy"),
            rationale="Tape-strip protocols excluded; healthy biopsies are 'other'.",
        ),
        "GSE83645": _pso(
            group_from="tissue type",
            groups={"psoriasis": Group.CASE, "uninvolved": Group.CONTROL},
            contrast="lesional_vs_nonlesional",
            case_label="psoriasis plaque",
            control_label="psoriasis uninvolved skin",
            fields={"donor": "patient id"},
            blocking="donor",
            constant={"tissue": "skin"},
            rationale="5 patients x 4 plaques + 1 uninvolved: plaques are summed per patient.",
        ),
        "GSE117405": _pso(
            group_from="disease state",
            groups={
                "psoriasis": Group.CASE,
                "healthy control": Group.CONTROL,
                "scalp psoriasis": Group.OTHER,
                "palmoplantar psoriasis": Group.OTHER,
            },
            contrast="lesional_vs_healthy",
            case_label="conventional psoriasis lesional skin",
            control_label="healthy skin",
            constant={"tissue": "skin"},
            rationale="Scalp and palmoplantar psoriasis kept as 'other'.",
        ),
        "GSE205748": _pso(
            group_from="tissue type",
            groups={
                "Psoriatic arthritis skin lesion": Group.CASE,
                "Healthy control skin": Group.CONTROL,
                "Psoriatic arthritis skin uninvolved": Group.OTHER,
            },
            contrast="lesional_vs_healthy",
            case_label="psoriatic arthritis lesional skin",
            control_label="healthy skin",
            constant={"tissue": "skin"},
            rationale="Uninvolved PsA skin kept as 'other'.",
        ),
        "GSE142582": _pso(
            group_from="tissue subtype",
            groups={
                "Psoriatic plaque tissue (PS)": Group.CASE,
                "healthy skin control": Group.CONTROL,
                "adjacent normal skin tissue (PN)": Group.OTHER,
            },
            contrast="lesional_vs_healthy",
            case_label="psoriasis plaque",
            control_label="healthy skin",
            fields={"age": "age"},
            constant={"tissue": "skin"},
            rationale="5 vs 5; adjacent non-lesional skin kept as 'other'.",
        ),
        "GSE63979": _pso(
            group_from="tissue type",
            groups={
                "psoriatic skin": Group.CASE,
                "normal skin": Group.CONTROL,
                "Uninvolved skin": Group.OTHER,
            },
            contrast="lesional_vs_healthy",
            case_label="psoriasis lesional skin",
            control_label="healthy skin",
            constant={"tissue": "skin"},
            rationale="7 vs 8; 27 uninvolved samples kept as 'other'.",
        ),
        "GSE249936": _pso(
            group_from="disease state",
            groups={
                "psoriasis skin lesion": Group.CASE,
                "non-lesional skin": Group.CONTROL,
                "psoriasis skin lesion after treatment": Group.OTHER,
            },
            contrast="lesional_vs_nonlesional",
            case_label="psoriasis lesional skin, untreated",
            control_label="psoriasis non-lesional skin",
            fields={
                "donor": _title_re(r"^(A\d+)_"),
                "sex": "Sex",
                "age": "age",
                "treatment": "treatment",
            },
            blocking="donor",
            constant={"tissue": "skin"},
            rationale="Dithranol-treated lesions kept as 'other'; 5 of 8 patients have both arms.",
        ),
        "GSE197056": _pso(
            group_from="tissue",
            groups={"LS": Group.CASE, "NL": Group.CONTROL},
            contrast="lesional_vs_nonlesional",
            case_label="psoriasis lesional skin, baseline",
            control_label="psoriasis non-lesional skin, baseline",
            fields={"donor": "individual", "treatment": "treatment", "time_point": "timepoint"},
            blocking="donor",
            constant={"tissue": "skin"},
            exclude=_char_not("timepoint", "BL"),
            rationale="Ustekinumab-resistant patients at baseline; week-16 biopsies excluded.",
        ),
    }
)


def _get(s: GeoSample, chars: dict[str, str], getter: Getter) -> str | None:
    if callable(getter):
        return getter(s, chars)
    return chars.get(getter)


def build(gse: str, rules: Rules) -> tuple[SampleSheet, Contrast]:
    series = read_soft(DATA / gse / f"{gse}_family.soft.gz")
    samples: list[Sample] = []
    for s in series.samples:
        chars = s.characteristics_dict()
        if rules.exclude is not None and rules.exclude(s, chars):
            continue
        if callable(rules.group_from):
            key_value, evidence = rules.group_from(s, chars)
        elif rules.group_from == "source_name":
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


QUERY_SETS = {
    "hcc_tumor_vs_adjacent": {
        "question": "Which genes differ between HCC tumor and adjacent non-tumor liver?",
        "case_label": "HCC tumor",
        "control_label": "adjacent non-tumor liver",
        "stratum": lambda _rules: None,
        "markers_up": HCC_UP,
        "markers_down": HCC_DOWN,
        "genes_of_interest": ["GPC3", "AFP", "GLUL", "CYP2E1", "TERT", "MKI67"],
    },
    "psoriasis_lesional_vs_control": {
        "question": "Which genes differ between psoriasis lesional skin and control skin?",
        "case_label": "psoriasis lesional skin",
        "control_label": "control skin (healthy or non-lesional)",
        # the stratum is the kind of control, not the contrast's own name
        "stratum": lambda rules: PSO_STRATA[rules.contrast],
        "markers_up": PSO_UP,
        "markers_down": [],
        "genes_of_interest": ["IL17A", "IL23A", "IL36G", "DEFB4A", "KRT16", "FLG", "LOR"],
    },
}
SETS_DIR = FIXTURES.parent / "query_sets"


def write_query_sets() -> None:
    SETS_DIR.mkdir(parents=True, exist_ok=True)
    for name, spec in QUERY_SETS.items():
        members = [
            {"gse": gse, "contrast": r.contrast, "stratum": spec["stratum"](r)}  # type: ignore[operator]
            for gse, r in RULES.items()
            if name in r.query_sets
        ]
        doc = {
            "name": name,
            "question": spec["question"],
            "case_label": spec["case_label"],
            "control_label": spec["control_label"],
            "members": members,
            "markers": [
                *({"symbol": g, "direction": "up"} for g in spec["markers_up"]),  # type: ignore[attr-defined]
                *({"symbol": g, "direction": "down"} for g in spec["markers_down"]),  # type: ignore[attr-defined]
            ],
            "genes_of_interest": spec["genes_of_interest"],
        }
        (SETS_DIR / f"{name}.json").write_text(json.dumps(doc, indent=1) + "\n")
        print(f"query set {name}: {len(members)} members -> {SETS_DIR / f'{name}.json'}")


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    write_query_sets()
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
