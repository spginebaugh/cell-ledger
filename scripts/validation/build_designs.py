"""Design files (sample sheet + confirmed contrasts) for the published-DE validation.

Labels are read from the GEO SOFT metadata downloaded by ``fetch_published.py`` and every
label cites the verbatim GEO string it keys on, so the files pass the SampleSheet contract.
Written to ``scripts/validation/designs/<GSE>.json``; run one with

    uv run cell-ledger run GSE52778 --design scripts/validation/designs/GSE52778.json

GSE144269 reuses the hand-curated example design and adds one paired contrast per Candia
2020 molecular subclass (MO1-MO4), because the authors published fold changes per subclass.
The patient of each GEO sample is the RNA-seq id in its title (``pat 10 tumor [HDV_10A_S33]``)
looked up in the paper's Source Data ``Samples`` sheet; the subclass comes from ``Fig. 1c``.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import openpyxl

from cell_ledger.geo import GeoSample, read_soft
from cell_ledger.samplesheet import (
    Assay,
    Contrast,
    ContrastStatus,
    Group,
    Sample,
    SampleSheet,
)

ROOT = Path(__file__).parents[2]
GEO = ROOT / "data" / "geo"
PUBLISHED = ROOT / "data" / "published"
OUT = Path(__file__).parent / "designs"
EXAMPLES = ROOT / "packages" / "core" / "tests" / "fixtures" / "geo_examples"


def sample(s: GeoSample, group: Group, evidence: str, **fields: Any) -> Sample:
    chars = s.characteristics_dict()
    labelled = group is not Group.UNKNOWN
    return Sample(
        gsm=s.gsm,
        title=s.title,
        source_name=s.source_name,
        group=group,
        organism=s.organism,
        evidence=[evidence] if labelled else [],
        confidence=1.0 if labelled else None,
        raw=chars,
        raw_lines=list(s.characteristics),
        **fields,
    )


def write(
    gse: str,
    title: str,
    samples: list[Sample],
    contrasts: list[Contrast],
    markers: list[dict[str, Any]] | None = None,
) -> None:
    sheet = SampleSheet(gse=gse, assay=Assay.BULK, title=title, samples=samples)
    for c in contrasts:
        problems = c.problems(sheet)
        if problems:
            raise SystemExit(f"{gse} {c.name}: {problems}")
    doc = {
        "samplesheet": sheet.model_dump(mode="json"),
        "contrasts": [c.model_dump(mode="json") for c in contrasts],
        "markers": markers or [],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{gse}.json").write_text(json.dumps(doc, indent=1))
    for c in contrasts:
        print(
            f"{gse} {c.name}: {len(c.case_gsms)} case vs {len(c.control_gsms)} control,"
            f" blocking={c.blocking}"
        )


def confirmed(gse: str, name: str, **kw: Any) -> Contrast:
    return Contrast(gse=gse, name=name, status=ContrastStatus.CONFIRMED, confidence=1.0, **kw)


def gse52778() -> None:
    """Dexamethasone vs untreated airway smooth muscle cells, four donor lines."""
    gse = "GSE52778"
    series = read_soft(GEO / gse / f"{gse}_family.soft.gz")
    groups = {"Dexamethasone": Group.CASE, "Untreated": Group.CONTROL}
    samples, case, ctrl = [], [], []
    for s in series.samples:
        c = s.characteristics_dict()
        treatment = c["treatment"]
        group = groups.get(treatment, Group.OTHER)  # albuterol arms stay in the sheet as other
        samples.append(
            sample(
                s,
                group,
                f"treatment: {treatment}",
                treatment=treatment,
                condition=treatment,
                donor=c["cell line"],
                cell_line=c["cell line"],
                cell_type=c.get("cell type"),
                tissue=c.get("tissue"),
            )
        )
        if group is Group.CASE:
            case.append(s.gsm)
        elif group is Group.CONTROL:
            ctrl.append(s.gsm)
    labels = {"case_label": "dexamethasone 1 uM 18 h", "control_label": "untreated"}
    write(
        gse,
        series.title,
        samples,
        [
            confirmed(
                gse,
                "dex_vs_untreated",
                case_gsms=case,
                control_gsms=ctrl,
                blocking="donor",
                rationale="Himes 2014 (PMID 24926665); paired by donor cell line.",
                **labels,
            ),
            confirmed(
                gse,
                "dex_vs_untreated_unpaired",
                case_gsms=case,
                control_gsms=ctrl,
                rationale="Same samples fitted ~arm only, like the pooled Cuffdiff run on GEO.",
                **labels,
            ),
        ],
    )


# (GEO series prefix, infected label in the title) -> (contrast, case label, control label)
GSE147507_PLAN = {
    ("Series1_NHBE", "SARS-CoV-2"): (
        "nhbe_sarscov2_vs_mock",
        "NHBE SARS-CoV-2 MOI 2, 24 h",
        "NHBE mock",
    ),
    ("Series2_A549", "SARS-CoV-2"): (
        "a549_sarscov2_moi02_vs_mock",
        "A549 SARS-CoV-2 MOI 0.2, 24 h",
        "A549 mock",
    ),
    ("Series5_A549", "SARS-CoV-2"): (
        "a549_sarscov2_moi2_vs_mock",
        "A549 SARS-CoV-2 MOI 2, 24 h",
        "A549 mock",
    ),
    ("Series7_Calu3", "SARS-CoV-2"): (
        "calu3_sarscov2_vs_mock",
        "Calu-3 SARS-CoV-2 MOI 2, 24 h",
        "Calu-3 mock",
    ),
    ("Series8_A549", "RSV"): ("a549_rsv_vs_mock", "A549 RSV MOI 2, 24 h", "A549 mock"),
    ("Series8_A549", "HPIV3"): ("a549_hpiv3_vs_mock", "A549 HPIV3 MOI 3, 24 h", "A549 mock"),
    ("Series9_NHBE", "IAV"): ("nhbe_iav_vs_mock", "NHBE IAV MOI 3, 12 h", "NHBE mock"),
    ("Series9_NHBE", "IAVdNS1"): ("nhbe_iavdns1_vs_mock", "NHBE IAVdNS1 MOI 3, 12 h", "NHBE mock"),
}


def gse147507() -> None:
    """Blanco-Melo 2020: virus-infected vs mock cell lines, one contrast per GEO series.

    Ferret samples and the COVID-19 lung biopsies are left out: the former are not human,
    the latter (and the A549-ACE2 infections) were not quantified by NCBI.
    """
    gse = "GSE147507"
    series = read_soft(GEO / gse / f"{gse}_family.soft.gz")
    record = json.loads((GEO / gse / "dataset.json").read_text())
    counted = {x["gsm"] for x in record["samples"] if x["in_counts"]}
    samples: list[Sample] = []
    arms: dict[str, dict[str, list[str]]] = {}
    for s in series.samples:
        if "Ferret" in s.title or "Lung" in s.title:
            continue
        m = re.match(r"(Series\d+_[A-Za-z0-9-]+)_(.+)_(\d+)$", s.title)
        if not m:
            raise SystemExit(f"{gse}: unexpected title {s.title!r}")
        prefix, label = m.group(1), m.group(2)
        c = s.characteristics_dict()
        if label == "Mock":
            group = Group.CONTROL
        elif (prefix, label) in GSE147507_PLAN:
            group = Group.CASE
        else:
            group = Group.OTHER
        samples.append(
            sample(
                s,
                group,
                s.title,
                treatment=c.get("treatment"),
                condition=label,
                cell_line=c.get("cell line") or prefix.split("_", 1)[1],
                batch=prefix,
                time_point=c.get("time point") or c.get("time after treatment"),
            )
        )
        arms.setdefault(prefix, {}).setdefault(label, []).append(s.gsm)
    contrasts = [
        confirmed(
            gse,
            name,
            case_label=case_label,
            control_label=control_label,
            case_gsms=[g for g in arms[prefix][label] if g in counted],
            control_gsms=[g for g in arms[prefix]["Mock"] if g in counted],
            restricted_to={"batch": prefix},
            rationale=(
                f"Blanco-Melo 2020 (PMID 32416070), {prefix}: infected vs mock within one "
                "series; DESeq2 in the paper."
            ),
        )
        for (prefix, label), (name, case_label, control_label) in GSE147507_PLAN.items()
    ]
    write(gse, series.title, samples, contrasts)


def gse144269() -> None:
    """Candia 2020 HCC: the example design plus one paired contrast per molecular subclass."""
    gse = "GSE144269"
    doc = json.loads((EXAMPLES / f"{gse}.json").read_text())
    sheet = SampleSheet.model_validate(doc["samplesheet"])
    base = Contrast.model_validate(doc["contrasts"][0])
    source = PUBLISHED / gse / "europepmc" / "41467_2020_18186_MOESM22_ESM.xlsx"
    wb = openpyxl.load_workbook(source, read_only=True)
    rows = list(wb["Samples"].iter_rows(values_only=True))
    header = [str(h) for h in rows[0]]
    patient_of_rna: dict[str, str] = {}
    for r in rows[1:]:
        rec = dict(zip(header, r, strict=False))
        for key in ("RNASeq_T", "RNASeq_NT"):
            if rec.get(key) not in (None, "NA"):
                patient_of_rna[str(rec[key])] = str(rec["Patient"])
    classes = list(wb["Fig. 1c"].iter_rows(values_only=True))[1:]
    subclass = {str(r[0]): str(r[1]) for r in classes}
    class_of_gsm: dict[str, str] = {}
    for s in sheet.samples:
        m = re.search(r"\[(HDV_\d+[AB]_S\d+)\]", s.title)
        patient = patient_of_rna.get(m.group(1)) if m else None
        class_of_gsm[s.gsm] = subclass.get(patient, "NA") if patient else "unmatched"
    print(f"{gse} samples per subclass: {dict(Counter(class_of_gsm.values()))}")
    contrasts = [base]
    for mo in ("MO1", "MO2", "MO3", "MO4"):
        contrasts.append(
            confirmed(
                gse,
                f"tumor_vs_adjacent_{mo.lower()}",
                case_label=f"{base.case_label} ({mo} subclass)",
                control_label=base.control_label,
                case_gsms=[g for g in base.case_gsms if class_of_gsm[g] == mo],
                control_gsms=[g for g in base.control_gsms if class_of_gsm[g] == mo],
                blocking="donor",
                rationale=(
                    f"Candia 2020 (PMID 32873799) molecular subclass {mo} patients only; "
                    "subclass from Source Data Fig. 1c, patient from the RNA-seq id in the "
                    "GEO title."
                ),
            )
        )
    write(gse, sheet.title or gse, list(sheet.samples), contrasts, doc.get("markers"))


def main() -> int:
    gse52778()
    gse147507()
    gse144269()
    return 0


if __name__ == "__main__":
    sys.exit(main())
