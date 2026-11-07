"""Download the curated example datasets into data/geo (gitignored).

Per series: NCBI-generated raw counts (GRCh38.p13, HISAT2 + featureCounts) and the
family SOFT metadata file; plus the shared human gene annotation table. Writes
data/geo/manifest.json with URLs, md5s and matrix checks.

Use the FTP host: the /geo/download/ web endpoint answers HEAD with an empty 200
whether or not a file exists and sometimes serves a reCAPTCHA page.

    uv run python scripts/fetch_geo_examples.py [GSE ...]
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


if __name__ == "__main__":
    main(sys.argv[1:] or EXAMPLE_GSES)
