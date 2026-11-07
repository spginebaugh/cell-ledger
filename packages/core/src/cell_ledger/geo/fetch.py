"""Download one GEO series in the layout the downstream pipeline reads.

Per series, into ``<root>/<GSE>/``:

- ``<GSE>_raw_counts_GRCh38.p13_NCBI.tsv.gz``  NCBI raw counts, byte-for-byte as served
- ``<GSE>_family.soft.gz``                     per-sample metadata (evidence source)
- ``dataset.json``                             provenance + per-sample checks (DatasetRecord)

plus the shared ``<root>/annotation/Human.GRCh38.p13.annot.tsv.gz``, pulled once.

Files never get rewritten: excluded samples are recorded in ``dataset.json`` and the
counts matrix stays as downloaded (downstream reconciles columns against the sheet).
Everything comes from the FTP host; the ``/geo/download/`` web endpoint can serve a
reCAPTCHA page and its HEAD always answers 200.
"""

from __future__ import annotations

import gzip
import hashlib
import re
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

import httpx
from pydantic import BaseModel, Field

from cell_ledger.geo.soft import read_soft

FTP = "https://ftp.ncbi.nlm.nih.gov/geo"
ANNOTATION_NAME = "Human.GRCh38.p13.annot.tsv.gz"
ANNOTATION_URL = f"{FTP}/rnaseq_counts/annot/{ANNOTATION_NAME}"
HUMAN = "Homo sapiens"
RNA_SEQ = "RNA-Seq"


class SampleExclusion(StrEnum):
    NOT_HUMAN = "not_human"
    NOT_RNA_SEQ = "not_rna_seq"
    NOT_IN_COUNTS = "not_in_counts"


class DatasetExclusion(StrEnum):
    NO_NCBI_COUNTS = "no_ncbi_counts"
    COUNTS_NOT_INTEGER = "counts_not_integer"
    NO_ELIGIBLE_SAMPLES = "no_eligible_samples"


class FileRecord(BaseModel):
    name: str
    url: str
    md5: str
    bytes: int
    downloaded_at: datetime


class SampleRecord(BaseModel):
    """One GSM as GEO describes it. Values are verbatim from the SOFT file."""

    gsm: str
    title: str
    source_name: str
    organism: str
    library_strategy: str
    characteristics: list[str]
    in_counts: bool
    exclusions: list[SampleExclusion] = Field(default_factory=list)

    @property
    def eligible(self) -> bool:
        return not self.exclusions


class CountsCheck(BaseModel):
    n_genes: int
    n_columns: int
    all_nonneg_integers: bool
    columns_not_in_soft: list[str]


class DatasetRecord(BaseModel):
    gse: str
    status: str = Field(description="'ready' or 'excluded'")
    exclusions: list[DatasetExclusion] = Field(default_factory=list)
    title: str = ""
    summary: str = ""
    overall_design: str = ""
    pubmed_ids: list[str] = Field(default_factory=list)
    files: dict[str, FileRecord] = Field(default_factory=dict, description="'counts', 'soft'")
    counts_check: CountsCheck | None = None
    samples: list[SampleRecord] = Field(default_factory=list)
    n_eligible: int = 0


def series_stem(gse: str) -> str:
    """GEO groups series in folders of 1000: GSE164073 -> GSE164nnn, GSE1 -> GSEnnn."""
    return gse[:-3] + "nnn" if len(gse) > 6 else "GSEnnn"


def counts_name(gse: str) -> str:
    return f"{gse}_raw_counts_GRCh38.p13_NCBI.tsv.gz"


def counts_url(gse: str, name: str | None = None) -> str:
    return f"{FTP}/rnaseq_counts/{series_stem(gse)}/{name or counts_name(gse)}"


def soft_url(gse: str) -> str:
    return f"{FTP}/series/{series_stem(gse)}/{gse}/soft/{gse}_family.soft.gz"


def _md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


async def _download(http: httpx.AsyncClient, url: str, dest: Path) -> FileRecord:
    """Stream ``url`` to ``dest`` atomically; reuse ``dest`` if already present."""
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        async with http.stream("GET", url) as r:
            r.raise_for_status()
            with tmp.open("wb") as f:
                async for chunk in r.aiter_bytes():
                    f.write(chunk)
        tmp.replace(dest)
    stat = dest.stat()
    return FileRecord(
        name=dest.name,
        url=url,
        md5=_md5(dest),
        bytes=stat.st_size,
        downloaded_at=datetime.fromtimestamp(stat.st_mtime, UTC),
    )


async def _find_counts(http: httpx.AsyncClient, gse: str) -> str | None:
    """Raw-counts filename for ``gse``, or None when NCBI has not generated counts.

    Tries the current naming first, then the folder listing in case the reference
    build in the filename has changed.
    """
    r = await http.head(counts_url(gse))
    if r.status_code == 200:
        return counts_name(gse)
    if r.status_code != 404:
        r.raise_for_status()
    listing = await http.get(f"{FTP}/rnaseq_counts/{series_stem(gse)}/")
    if listing.status_code == 404:
        return None
    listing.raise_for_status()
    found = re.findall(rf'href="({gse}_raw_counts_[^"/]+\.tsv\.gz)"', listing.text)
    return found[0] if found else None


def check_counts(path: Path, soft_gsms: set[str]) -> tuple[CountsCheck, list[str]]:
    """Header and value checks without loading the matrix into memory."""
    with gzip.open(path, "rt") as f:
        columns = f.readline().rstrip("\n").split("\t")[1:]
        n_genes, all_int = 0, True
        for line in f:
            n_genes += 1
            if all_int and not all(v.isdigit() for v in line.rstrip("\n").split("\t")[1:]):
                all_int = False
    check = CountsCheck(
        n_genes=n_genes,
        n_columns=len(columns),
        all_nonneg_integers=all_int,
        columns_not_in_soft=[c for c in columns if c not in soft_gsms],
    )
    return check, columns


async def ensure_annotation(http: httpx.AsyncClient, root: Path) -> FileRecord:
    """The shared human annotation table, downloaded once into ``root/annotation``."""
    return await _download(http, ANNOTATION_URL, root / "annotation" / ANNOTATION_NAME)


async def fetch_series(http: httpx.AsyncClient, gse: str, root: Path) -> DatasetRecord:
    """Download and check one series into ``root/<gse>``; writes and returns its record."""
    if not re.fullmatch(r"GSE\d+", gse):
        raise ValueError(f"not a GEO series accession: {gse!r}")
    out = root / gse
    out.mkdir(parents=True, exist_ok=True)

    name = await _find_counts(http, gse)
    if name is None:
        record = DatasetRecord(
            gse=gse, status="excluded", exclusions=[DatasetExclusion.NO_NCBI_COUNTS]
        )
        _write(out, record)
        return record

    soft_file = await _download(http, soft_url(gse), out / f"{gse}_family.soft.gz")
    counts_file = await _download(http, counts_url(gse, name), out / name)
    series = read_soft(out / soft_file.name)
    check, columns = check_counts(out / name, {s.gsm for s in series.samples})
    in_counts = set(columns)

    samples: list[SampleRecord] = []
    for s in series.samples:
        reasons: list[SampleExclusion] = []
        if s.organism != HUMAN:
            reasons.append(SampleExclusion.NOT_HUMAN)
        if s.library_strategy != RNA_SEQ:
            reasons.append(SampleExclusion.NOT_RNA_SEQ)
        if s.gsm not in in_counts:
            reasons.append(SampleExclusion.NOT_IN_COUNTS)
        samples.append(
            SampleRecord(
                gsm=s.gsm,
                title=s.title,
                source_name=s.source_name,
                organism=s.organism,
                library_strategy=s.library_strategy,
                characteristics=s.characteristics,
                in_counts=s.gsm in in_counts,
                exclusions=reasons,
            )
        )

    n_eligible = sum(s.eligible for s in samples)
    exclusions: list[DatasetExclusion] = []
    if not check.all_nonneg_integers:
        exclusions.append(DatasetExclusion.COUNTS_NOT_INTEGER)
    if n_eligible == 0:
        exclusions.append(DatasetExclusion.NO_ELIGIBLE_SAMPLES)

    record = DatasetRecord(
        gse=gse,
        status="excluded" if exclusions else "ready",
        exclusions=exclusions,
        title=series.title,
        summary=series.summary,
        overall_design=series.overall_design,
        pubmed_ids=series.pubmed_ids,
        files={"counts": counts_file, "soft": soft_file},
        counts_check=check,
        samples=samples,
        n_eligible=n_eligible,
    )
    _write(out, record)
    return record


def _write(out: Path, record: DatasetRecord) -> None:
    (out / "dataset.json").write_text(record.model_dump_json(indent=2))
