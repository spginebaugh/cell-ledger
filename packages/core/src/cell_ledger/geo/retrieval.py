"""GEO discovery and metadata retrieval through the shared cache."""

import json
import re
from html import unescape
from urllib.parse import urljoin

from cell_ledger.bulk import sample_eligibility
from cell_ledger.geo.cache import CachedClient
from cell_ledger.geo.client import EUTILS, GeoSeriesHit
from cell_ledger.geo.models import GeoError, GeoSeries, parse_soft

GEO = "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi"


async def search_geo(
    client: CachedClient, query: str, *, limit: int = 20, since: int | None = None
) -> list[GeoSeriesHit]:
    if not 1 <= limit <= 100:
        raise ValueError("Search limit must be between 1 and 100")
    term = (
        f'({query}) AND GSE[ETYP] AND "Homo sapiens"[Organism] '
        'AND "expression profiling by high throughput sequencing"[DataSet Type]'
    )
    if since is not None:
        term += f' AND ("{since}"[PDAT] : "3000"[PDAT])'
    raw, _ = await client.get(
        f"{EUTILS}/esearch.fcgi",
        {
            "db": "gds",
            "term": term,
            "retmax": str(limit),
            "retmode": "json",
        },
    )
    response = json.loads(raw)
    if "esearchresult" not in response or response["esearchresult"].get("errorlist"):
        raise GeoError("NCBI rejected the search query")
    ids = response["esearchresult"]["idlist"]
    if not ids:
        return []
    raw, _ = await client.get(
        f"{EUTILS}/esummary.fcgi",
        {
            "db": "gds",
            "id": ",".join(ids),
            "retmode": "json",
        },
    )
    result = json.loads(raw).get("result", {})
    hits = {}
    for uid in ids:
        doc = result.get(uid, {})
        accession = doc.get("accession") or f"GSE{doc.get('gse', '')}"
        if not re.fullmatch(r"GSE\d+", accession):
            continue
        hits[accession] = GeoSeriesHit(
            gse=accession,
            title=doc.get("title", ""),
            summary=doc.get("summary", ""),
            taxa=[taxon.strip() for taxon in doc.get("taxon", "").split(";") if taxon.strip()],
            series_types=[
                kind.strip() for kind in doc.get("gdstype", "").split(";") if kind.strip()
            ],
            published=None,
            pubmed_ids=[str(pmid) for pmid in doc.get("pubmedids", [])],
            matched_queries=[query],
            n_samples=int(doc.get("n_samples", 0)),
        )
    return list(hits.values())


async def get_series_metadata(client: CachedClient, gse: str) -> GeoSeries:
    if not re.fullmatch(r"GSE\d+", gse):
        raise GeoError("Expected a GEO Series accession (GSE followed by digits)")
    params = {"acc": gse, "targ": "all", "view": "full", "form": "text"}
    raw, provenance = await client.get(GEO, params)
    return parse_soft(raw.decode("utf-8"), gse, provenance["url"])


async def expression_sources(client: CachedClient, series: GeoSeries) -> list[dict[str, str]]:
    """Discover actual reference/version filenames; never treat a HEAD 200 as counts."""
    listing_url = "https://www.ncbi.nlm.nih.gov/geo/download/"
    page, _ = await client.get(listing_url, {"acc": series.gse, "type": "rnaseq_counts"})
    html = page.decode("utf-8")
    if "Checking your browser" in html or "recaptcha" in html:
        raise GeoError("NCBI blocked the count-file listing; availability cannot be verified")
    urls = [unescape(url) for url in re.findall(r'href=["\x27]([^"\x27]+)', html)]
    urls += series.fields.get("supplementary_file", [])
    sources: dict[str, dict[str, str]] = {}
    annotations = [urljoin(listing_url, url) for url in urls if ".annot.tsv" in url]
    for raw_url in urls:
        url = urljoin(listing_url, raw_url).replace(
            "ftp://ftp.ncbi.nlm.nih.gov", "https://ftp.ncbi.nlm.nih.gov"
        )
        lower = url.lower()
        if "rnaseq_counts" in lower and "raw_counts" in lower and series.gse in url:
            sources[url] = {"url": url, "kind": "counts", "rule": "NCBI-generated raw counts"}
        elif "rnaseq_counts" in lower and "norm_counts_tpm" in lower and series.gse in url:
            sources[url] = {"url": url, "kind": "tpm", "rule": "NCBI-generated TPM"}
        elif raw_url in series.fields.get("supplementary_file", []):
            if not re.search(r"\.(tsv|csv|txt)(\.gz)?$", lower):
                continue
            # A filename alone does not establish expression units.
            kind = "unknown"
            # Only declarations describing the supplementary file establish units.
            declarations = [
                [
                    value
                    for value in sample.values("data_processing")
                    if value.lower().startswith("supplementary files format and content:")
                ]
                for sample in series.samples
                if not sample_eligibility(sample)
            ]
            evidence = [values[0] for values in declarations if len(values) == 1]
            if declarations and len(evidence) == len(declarations):
                if all(re.search(r"\bCPM\b|counts per million", value, re.I) for value in evidence):
                    kind = "normalized"
                elif all(re.search(r"\braw (?:read )?counts\b", value, re.I) for value in evidence):
                    kind = "counts"
            sources[url] = {
                "url": url,
                "kind": kind,
                "rule": "Submitter tabular fallback; review required",
            }
            if kind != "unknown":
                sources[url]["units_evidence"] = "\n".join(sorted(set(evidence)))
    for source in sources.values():
        reference = re.search(r"GRCh[\w.]+?(?=_NCBI)", source["url"])
        if reference:
            matches = [url for url in annotations if reference.group() in url]
            if len(matches) == 1:
                source["annotation_url"] = matches[0]
    return sorted(
        sources.values(),
        key=lambda source: (
            source["rule"] != "NCBI-generated raw counts",
            source["kind"] != "tpm",
            not bool(re.search(r"count|raw", source["url"], re.I)),
            source["url"],
        ),
    )
