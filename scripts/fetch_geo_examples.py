"""Download the curated example datasets into data/geo (gitignored).

Per series: NCBI-generated raw counts (GRCh38.p13, HISAT2 + featureCounts) and the
family SOFT metadata file; plus the shared human gene annotation table. Writes
data/geo/manifest.json with URLs, md5s and matrix checks.

Use the FTP host: the /geo/download/ web endpoint answers HEAD with an empty 200
whether or not a file exists and sometimes serves a reCAPTCHA page.

    uv run python scripts/fetch_geo_examples.py              # every set below
    uv run python scripts/fetch_geo_examples.py --set hcc_tumor_vs_adjacent
    uv run python scripts/fetch_geo_examples.py GSE82227 ...  # explicit accessions
"""

from __future__ import annotations

import gzip
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from cell_ledger.geo import read_soft

# Ten mixed-topic series used to build the single-dataset pipeline (one or two per topic).
EXAMPLE_GSES = [
    "GSE114286",
    "GSE67785",
    "GSE185492",
    "GSE79544",
    "GSE135631",
    "GSE140343",
    "GSE232753",
    "GSE233547",
    "GSE111414",
    "GSE82227",
]

# Multi-dataset sets: many series answering the same contrast, for the cross-dataset
# comparison layer. Vetted from SOFT metadata on 2026-11-07 (GEO esearch with the
# "rnaseq counts" filter); each has NCBI raw counts. Notes name the trap each one carries.
QUERY_SETS: dict[str, list[str]] = {
    # HCC tumor vs adjacent non-tumor liver tissue, almost all paired by patient.
    "hcc_tumor_vs_adjacent": [
        "GSE135631",  # 15 pairs (already in EXAMPLE_GSES)
        "GSE77314",  # 50 pairs; `diagnosis`: Tumor / Normal
        "GSE124535",  # 35 pairs; `tissue`: HCC / non-tumor
        "GSE144269",  # 70 pairs, Mongolian cohort; `tumor/non-tumor`
        "GSE202069",  # 41 tumor / 25 non-tumor, 17 tumors post anti-PD-1 (treatment sub-factor)
        "GSE169289",  # 17 pairs
        "GSE104310",  # 12 tumor / 8 non-tumor, paired by `individual`; HBV + cirrhosis covariates
        "GSE202853",  # 10 pairs; SubSeries "[I]" of a SuperSeries (dependence check)
        "GSE81550",  # 3 pairs: minimum group size
        "GSE216613",  # 3 pairs; labels only in `tissue`, titles N1-3 / P1-3
        "GSE154211",  # 5 pairs, HCV vs NBNC etiology sub-factor
        "GSE77509",  # 20 adjacent / 20 primary / 20 PVTT: restrict to primary vs adjacent
        "GSE105130",  # 25 tumor / 27 adjacent (two extra adjacent samples)
        "GSE214846",  # 65 pairs
        "GSE138485",  # 32 pairs; no tissue characteristic, tumor/normal only in sample title (trap)
        "GSE146719",  # 6 RNA-seq + 6 miRNA-seq GSMs: mixed assay, drop the miRNA GSMs
        "GSE87410",  # pan-cancer 50 pairs; `tissue`=liver only; NCBI quantified 8 of 12 liver GSMs
    ],
    # Psoriasis lesional skin vs control skin (healthy, or paired non-lesional).
    "psoriasis_lesional_vs_control": [
        "GSE114286",  # 18 lesional / 8 healthy (already in EXAMPLE_GSES)
        "GSE67785",  # 14 PP / 14 PN paired (already in EXAMPLE_GSES)
        "GSE54456",  # 92 lesional / 82 normal: the large case-control reference set
        "GSE121212",  # PSO lesional / non-lesional / healthy; AD arm must be excluded
        "GSE154200",  # 178 paired psoriasis lesional / non-lesional; eczema excluded; 7 batches
        "GSE171012",  # bulk skin only (sorted T cells excluded); healthy vs pre-treatment lesional
        "GSE74697",  # 18 pre-treatment lesional vs 16 normal; post-adalimumab samples excluded
        "GSE186063",  # PsO + PsA lesion / non-lesion, AS skin as healthy
        "GSE47944",  # explants: restrict to `treatment`=Untreated; Lesion / Nonlesion / Healthy
        "GSE178197",  # restrict to `protocol`=Biopsy; tape-strip samples excluded
        "GSE83645",  # 5 patients x 4 plaques + 1 uninvolved: pseudo-replication trap
        "GSE117405",  # conventional psoriasis vs healthy; scalp / palmoplantar as other
        "GSE205748",  # psoriatic arthritis lesion / uninvolved / healthy, 9 each
        "GSE142582",  # 5 lesional / 5 non-lesional / 5 healthy
        "GSE63979",  # 7 psoriatic / 8 normal / 27 uninvolved
        "GSE249936",  # 8 untreated lesional / 5 non-lesional; dithranol-treated excluded
        "GSE197056",  # LS vs NL at baseline in ustekinumab-resistant patients; W16 excluded
    ],
}


def all_gses() -> list[str]:
    seen: dict[str, None] = dict.fromkeys(EXAMPLE_GSES)
    for gses in QUERY_SETS.values():
        seen.update(dict.fromkeys(gses))
    return list(seen)


def sets_of(gse: str) -> list[str]:
    return [name for name, gses in QUERY_SETS.items() if gse in gses]


FTP = "https://ftp.ncbi.nlm.nih.gov/geo"
ANNOT_URL = f"{FTP}/rnaseq_counts/annot/Human.GRCh38.p13.annot.tsv.gz"
OUT = Path(__file__).parents[1] / "data" / "geo"
HEADERS = {"User-Agent": "cell-ledger-dev/0.1 (+https://github.com)"}


def stem(gse: str) -> str:
    return gse[:-3] + "nnn"


def counts_url(gse: str) -> str:
    return f"{FTP}/rnaseq_counts/{stem(gse)}/{gse}_raw_counts_GRCh38.p13_NCBI.tsv.gz"


def soft_url(gse: str) -> str:
    return f"{FTP}/series/{stem(gse)}/{gse}/soft/{gse}_family.soft.gz"


def md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(client: httpx.Client, url: str, dest: Path) -> bool:
    if dest.exists():
        return False
    tmp = dest.with_suffix(dest.suffix + ".part")
    with client.stream("GET", url) as r:
        r.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    tmp.replace(dest)
    time.sleep(0.5)
    return True


def check_counts(path: Path, gsms: set[str]) -> dict[str, object]:
    with gzip.open(path, "rt") as f:
        header = f.readline().rstrip("\n").split("\t")
        cols = header[1:]
        n, all_int = 0, True
        for line in f:
            n += 1
            if all_int and not all(v.isdigit() for v in line.rstrip("\n").split("\t")[1:]):
                all_int = False
    return {
        "first_col": header[0],
        "n_genes": n,
        "n_cols": len(cols),
        "extra_cols": [c for c in cols if c not in gsms],
        "gsms_missing_from_counts": sorted(gsms - set(cols)),
        "all_nonneg_integers": all_int,
    }


def main(gses: list[str]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "annotation").mkdir(exist_ok=True)
    manifest_path = OUT / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"datasets": {}}
    manifest["downloaded_at"] = datetime.now(UTC).isoformat()

    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=120) as client:
        annot = OUT / "annotation" / "Human.GRCh38.p13.annot.tsv.gz"
        download(client, ANNOT_URL, annot)
        manifest["annotation"] = {
            "url": ANNOT_URL,
            "file": str(annot.relative_to(OUT)),
            "md5": md5(annot),
        }

        for gse in gses:
            d = OUT / gse
            d.mkdir(exist_ok=True)
            soft = d / f"{gse}_family.soft.gz"
            counts = d / f"{gse}_raw_counts_GRCh38.p13_NCBI.tsv.gz"
            download(client, soft_url(gse), soft)
            download(client, counts_url(gse), counts)
            series = read_soft(soft)
            gsms = {s.gsm for s in series.samples}
            check = check_counts(counts, gsms)
            manifest["datasets"][gse] = {
                "title": series.title,
                "query_sets": sets_of(gse),
                "n_gsm_in_soft": len(gsms),
                "library_strategy": sorted({s.library_strategy for s in series.samples}),
                "files": {
                    "raw_counts": {
                        "url": counts_url(gse),
                        "file": str(counts.relative_to(OUT)),
                        "md5": md5(counts),
                        "bytes": counts.stat().st_size,
                    },
                    "soft": {
                        "url": soft_url(gse),
                        "file": str(soft.relative_to(OUT)),
                        "md5": md5(soft),
                    },
                },
                "counts_check": check,
            }
            ok = check["all_nonneg_integers"] and not check["extra_cols"]
            n_missing = len(check["gsms_missing_from_counts"])  # type: ignore[arg-type]
            print(
                f"{gse}: {'OK' if ok else 'CHECK'} genes={check['n_genes']} "
                f"cols={check['n_cols']} missing_gsms={n_missing}"
            )

    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"wrote {manifest_path}")


def _parse(argv: list[str]) -> list[str]:
    if argv[:1] == ["--set"]:
        if len(argv) != 2 or argv[1] not in QUERY_SETS:
            sys.exit(f"--set takes one of: {', '.join(QUERY_SETS)}")
        return QUERY_SETS[argv[1]]
    return argv or all_gses()


if __name__ == "__main__":
    main(_parse(sys.argv[1:]))
