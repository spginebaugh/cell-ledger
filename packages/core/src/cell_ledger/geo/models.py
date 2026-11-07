"""Source records preserve repeated SOFT fields verbatim for evidence checks."""

from pydantic import BaseModel, Field


class GeoSample(BaseModel):
    gsm: str = Field(pattern=r"^GSM\d+$")
    fields: dict[str, list[str]] = Field(default_factory=dict)

    def values(self, key: str) -> list[str]:
        return self.fields.get(key, [])

    def value(self, key: str) -> str:
        return "\n".join(self.values(key))


class GeoSeries(BaseModel):
    gse: str = Field(pattern=r"^GSE\d+$")
    fields: dict[str, list[str]] = Field(default_factory=dict)
    samples: list[GeoSample] = Field(default_factory=list)
    source_url: str

    def value(self, key: str) -> str:
        return "\n".join(self.fields.get(key, []))


class GeoError(ValueError):
    """A retrieval failed or returned an invalid source record."""


class SeriesNotFound(GeoError):
    pass


def parse_soft(text: str, gse: str, source_url: str) -> GeoSeries:
    series = GeoSeries(gse=gse, source_url=source_url)
    current: dict[str, list[str]] | None = None
    found = False
    seen: set[str] = set()
    for line in text.splitlines():
        if line.startswith("^SERIES = "):
            found = line.removeprefix("^SERIES = ").strip() == gse
            current = series.fields if found else None
        elif line.startswith("^SAMPLE = "):
            gsm = line.removeprefix("^SAMPLE = ").strip()
            if gsm in seen:
                raise GeoError(f"Duplicate sample record: {gsm}")
            seen.add(gsm)
            sample = GeoSample(gsm=gsm)
            series.samples.append(sample)
            current = sample.fields
        elif line.startswith("^"):
            current = None
        elif current is not None and line.startswith("!") and " = " in line:
            key, value = line[1:].split(" = ", 1)
            key = key.removeprefix("Series_").removeprefix("Sample_")
            current.setdefault(key, []).append(value)
    if not found:
        raise SeriesNotFound(f"{gse} does not resolve to a GEO Series record")
    expected = set(series.fields.get("sample_id", []))
    if expected and expected != seen:
        raise GeoError(f"{gse}: SOFT sample records do not match the series sample list")
    return series
