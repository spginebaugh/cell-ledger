"""Synthetic two-group dataset with planted structure, used by every analysis test.

8 samples (4 case, 4 control) x 1500 genes. Planted: 50 genes up in case, 50 down,
one low-depth control, one control mislabelled female, a GSM in the sheet with no
counts column, and a counts column that is not in the sheet.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pytest

from cell_ledger.samplesheet import Assay, Contrast, ContrastStatus, Group, Sample, SampleSheet

N_GENES = 1500
UP = [str(i) for i in range(10, 60)]
DOWN = [str(i) for i in range(60, 110)]
SPECIAL = {"1": "MT-CO1", "2": "RPS4Y1", "3": "XIST", "4": "RPL3", "5": "SILENT"}


@dataclass
class Synthetic:
    counts: pd.DataFrame  # genes x samples
    annotation: pd.DataFrame
    sheet: SampleSheet
    contrast: Contrast
    up: list[str]
    down: list[str]


def make_synthetic(seed: int = 0) -> Synthetic:
    rng = np.random.default_rng(seed)
    gene_ids = [str(i) for i in range(1, N_GENES + 1)]
    case = [f"GSM{i}" for i in range(1, 5)]
    control = [f"GSM{i}" for i in range(5, 9)]
    samples = case + control
    mu = rng.lognormal(mean=4.0, sigma=1.5, size=N_GENES)
    x = rng.negative_binomial(n=8, p=8 / (8 + mu[:, None]), size=(N_GENES, len(samples)))
    df = pd.DataFrame(x, index=gene_ids, columns=samples)
    df.loc[UP, case] = (df.loc[UP, case] * 6 + 20).astype(int)
    df.loc[DOWN, control] = (df.loc[DOWN, control] * 6 + 20).astype(int)
    # sex markers: cases female (XIST high), controls male (RPS4Y1 high)
    df.loc["3", case], df.loc["3", control] = 2000, 0
    df.loc["2", case], df.loc["2", control] = 0, 2000
    df.loc["1", :] = 500  # mitochondrial gene, modest fraction
    df.loc["5", :] = 0  # never expressed -> filtered out
    df["GSM8"] = (df["GSM8"] * 0.02).astype(int)  # low depth control
    df["GSM999"] = df["GSM1"]  # column not in sheet
    df.index.name = "GeneID"

    annotation = pd.DataFrame(
        {
            "Symbol": [SPECIAL.get(g, f"G{g}") for g in gene_ids],
            "GeneType": ["protein-coding"] * N_GENES,
            "Length": [1000] * N_GENES,
        },
        index=pd.Index(gene_ids, name="GeneID"),
    )

    def sample(gsm: str, group: Group, sex: str) -> Sample:
        raw = {"condition": group.value, "Sex": sex}
        return Sample(
            gsm=gsm,
            title=f"{group.value} {gsm}",
            group=group,
            condition=group.value,
            sex=sex,
            raw=raw,
            evidence=[f"condition: {group.value}"],
            confidence=1.0,
        )

    sheet_samples = [sample(g, Group.CASE, "female") for g in case]
    sheet_samples += [sample(g, Group.CONTROL, "male") for g in control[:-1]]
    sheet_samples.append(sample(control[-1], Group.CONTROL, "female"))  # mislabelled sex
    sheet_samples.append(sample("GSM42", Group.CASE, "female"))  # in sheet, not in counts
    sheet = SampleSheet(gse="GSE1", assay=Assay.BULK, title="synthetic", samples=sheet_samples)
    contrast = Contrast(
        gse="GSE1",
        name="case_vs_control",
        case_label="case",
        control_label="control",
        case_gsms=[*case, "GSM42"],
        control_gsms=control,
        confidence=1.0,
        status=ContrastStatus.CONFIRMED,
    )
    return Synthetic(df, annotation, sheet, contrast, UP, DOWN)


@pytest.fixture(scope="session")
def synthetic() -> Synthetic:
    return make_synthetic()


@pytest.fixture(scope="session")
def synthetic_files(synthetic: Synthetic, tmp_path_factory: pytest.TempPathFactory):
    d = tmp_path_factory.mktemp("synthetic")
    counts = d / "GSE1_raw_counts.tsv.gz"
    annot = d / "annot.tsv.gz"
    synthetic.counts.to_csv(counts, sep="\t")
    synthetic.annotation.to_csv(annot, sep="\t")
    return counts, annot
