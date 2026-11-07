"""Parser for GEO family SOFT files (``GSE*_family.soft.gz``).

Only the series and sample sections are read; platform data tables are skipped.
Values are kept verbatim because they serve as evidence strings downstream.
"""

from __future__ import annotations

import gzip
from pathlib import Path

from pydantic import BaseModel, Field


class GeoSample(BaseModel):
    gsm: str
    title: str = ""
    source_name: str = ""
    organism: str = ""
    platform: str = ""
    library_strategy: str = ""
    characteristics: list[str] = Field(default_factory=list)

    def characteristics_dict(self) -> dict[str, str]:
        """``"key: value"`` lines as a dict; a repeated key gets a numeric suffix."""
        out: dict[str, str] = {}
        for line in self.characteristics:
            key, sep, value = line.partition(": ")
            if not sep:
                key, value = "characteristics", line
            k, i = key, 2
            while k in out:
                k, i = f"{key}.{i}", i + 1
            out[k] = value
        return out


class GeoSeries(BaseModel):
    gse: str
    title: str = ""
    summary: str = ""
    overall_design: str = ""
    pubmed_ids: list[str] = Field(default_factory=list)
    supplementary_files: list[str] = Field(default_factory=list)
    samples: list[GeoSample] = Field(default_factory=list)


_SAMPLE_SCALARS = {
    "!Sample_title": "title",
    "!Sample_source_name_ch1": "source_name",
    "!Sample_organism_ch1": "organism",
    "!Sample_platform_id": "platform",
    "!Sample_library_strategy": "library_strategy",
}


def parse_soft(text: str) -> GeoSeries:
    gse, title = "", ""
    pubmed_ids: list[str] = []
    supplementary_files: list[str] = []
    summary: list[str] = []
    design: list[str] = []
    samples: list[GeoSample] = []
    section = None  # "series" | "sample" | None
    cur: GeoSample | None = None

    for line in text.splitlines():
        if line.startswith("^SERIES"):
            section, cur = "series", None
            gse = line.partition(" = ")[2].strip()
        elif line.startswith("^SAMPLE"):
            section = "sample"
            cur = GeoSample(gsm=line.partition(" = ")[2].strip())
            samples.append(cur)
        elif line.startswith("^"):
            section, cur = None, None
        elif section == "series" and line.startswith("!Series_"):
            key, _, value = line[len("!Series_") :].partition(" = ")
            if key == "title":
                title = value
            elif key == "summary":
                summary.append(value)
            elif key == "overall_design":
                design.append(value)
            elif key == "pubmed_id":
                pubmed_ids.append(value)
            elif key.startswith("supplementary_file"):
                supplementary_files.append(value)
        elif section == "sample" and cur is not None:
            key, _, value = line.partition(" = ")
            if key == "!Sample_characteristics_ch1":
                cur.characteristics.append(value)
            elif key in _SAMPLE_SCALARS:
                setattr(cur, _SAMPLE_SCALARS[key], value)

    return GeoSeries(
        gse=gse,
        title=title,
        summary=" ".join(summary),
        overall_design=" ".join(design),
        pubmed_ids=pubmed_ids,
        supplementary_files=supplementary_files,
        samples=samples,
    )


def read_soft(path: str | Path) -> GeoSeries:
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as f:
        return parse_soft(f.read())
