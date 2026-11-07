"""Download the inputs for the published-DE validation (docs/validation/README.md).

Two kinds of files, both into gitignored ``data/``:

- ``data/geo/<GSE>/``: NCBI-generated raw counts and SOFT metadata for each validation
  series, through the same ``cell_ledger.geo.fetch`` code the app uses.
- ``data/published/<GSE>/``: the differential expression tables the authors published,
  taken from GEO supplementary files, bioRxiv supplementary media, or the Europe PMC
  supplementary-files bundle for the PMC record (Cell and Nature Communications host their
  tables behind bot checks; Europe PMC mirrors them as one zip per article).

    uv run python scripts/validation/fetch_published.py

Files already present are kept. Europe PMC answers 503 now and then; the download is
retried a few times.
"""

from __future__ import annotations

import asyncio
import io
import sys
import time
import zipfile
from pathlib import Path

import httpx

from cell_ledger.geo.fetch import ensure_annotation, fetch_series

ROOT = Path(__file__).parents[2]
GEO = ROOT / "data" / "geo"
PUBLISHED = ROOT / "data" / "published"

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
GEO_FTP = "https://ftp.ncbi.nlm.nih.gov/geo/series"
EUROPEPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"

# GEO series whose counts the validation runs on. GSE144269 is also an example dataset.
SERIES = ["GSE52778", "GSE147507", "GSE144269"]

# (GSE, filename, url): single published files.
FILES: list[tuple[str, str, str]] = [
    # Himes 2014, PLoS ONE 9:e99625 (PMID 24926665): Cuffdiff output deposited on GEO.
    (
        "GSE52778",
        "GSE52778_Dex_vs_Untreated_gene_exp.diff.gz",
        f"{GEO_FTP}/GSE52nnn/GSE52778/suppl/GSE52778_Dex_vs_Untreated_gene_exp.diff.gz",
    ),
    # Blanco-Melo 2020 bioRxiv v1 (2020.03.24.004655), Supplementary Table 2: the full
    # DESeq2 output for the A549 SARS-CoV-2 (MOI 0.2) experiment, GEO Series2.
    (
        "GSE147507",
        "biorxiv_media-2.xlsx",
        "https://www.biorxiv.org/content/biorxiv/early/2020/03/24/2020.03.24.004655/"
        "DC2/embed/media-2.xlsx",
    ),
]

# (GSE, PMC id): Europe PMC supplementary bundles, unzipped into data/published/<GSE>/europepmc.
BUNDLES: list[tuple[str, str]] = [
    ("GSE147507", "PMC7227586"),  # Blanco-Melo 2020, Cell 181:1036: Tables S1-S5 (mmc1-5.xlsx)
    ("GSE144269", "PMC7462863"),  # Candia 2020, Nat Commun 11:4383: Supplementary Data 1-18
]


def _get(client: httpx.Client, url: str, *, tries: int = 4) -> bytes:
    last = ""
    for attempt in range(tries):
        r = client.get(url)
        if r.status_code == 200 and not r.headers.get("content-type", "").startswith("text/html"):
            return r.content
        last = f"HTTP {r.status_code} {r.headers.get('content-type')}"
        if attempt + 1 < tries:
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"could not download {url}: {last}")


def fetch_published() -> None:
    with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True, timeout=120) as client:
        for gse, name, url in FILES:
            dest = PUBLISHED / gse / name
            if dest.exists():
                print(f"{gse}/{name}: present")
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(_get(client, url))
            print(f"{gse}/{name}: {dest.stat().st_size:,} bytes")
        for gse, pmc in BUNDLES:
            out = PUBLISHED / gse / "europepmc"
            if out.exists() and any(out.glob("*.xlsx")):
                print(f"{gse}/europepmc ({pmc}): present")
                continue
            out.mkdir(parents=True, exist_ok=True)
            blob = _get(client, f"{EUROPEPMC}/{pmc}/supplementaryFiles")
            if not blob.startswith(b"PK"):
                raise RuntimeError(f"{pmc}: Europe PMC answered {blob[:200]!r}")
            with zipfile.ZipFile(io.BytesIO(blob)) as zf:
                names = [n for n in zf.namelist() if n.lower().endswith((".xlsx", ".xls", ".csv"))]
                for n in names:
                    (out / Path(n).name).write_bytes(zf.read(n))
            print(f"{gse}/europepmc ({pmc}): {len(names)} tables")


async def fetch_geo() -> None:
    async with httpx.AsyncClient(timeout=httpx.Timeout(600.0), follow_redirects=True) as http:
        await ensure_annotation(http, GEO)
        for gse in SERIES:
            rec = await fetch_series(http, gse, GEO)
            n = rec.counts_check.n_columns if rec.counts_check else 0
            print(f"{gse}: {rec.status} {[e.value for e in rec.exclusions]} {n} columns counted")


def main() -> int:
    fetch_published()
    asyncio.run(fetch_geo())
    return 0


if __name__ == "__main__":
    sys.exit(main())
