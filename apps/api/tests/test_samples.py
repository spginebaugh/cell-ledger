"""Sample-level selection: the record summary Claude reads and the rules code applies."""

from __future__ import annotations

from typing import Any

import httpx

from cell_ledger.geo import GeoClient, GeoSample, GeoSeries
from cell_ledger.geo.fetch import counts_url, soft_url
from cell_ledger_api.agent.discover import Discoverer, DiscoveryOutput
from cell_ledger_api.agent.llm import quiet
from cell_ledger_api.agent.samples import (
    Condition,
    Rule,
    sample_fields,
    select_samples,
    series_digest,
)

from .test_agent import ESUMMARY, ScriptedTurns, message


def sample(gsm: str, title: str, *chars: str, **kw: Any) -> GeoSample:
    return GeoSample(gsm=gsm, title=title, characteristics=list(chars), **kw)


ORGANOIDS = GeoSeries(
    gse="GSE164073",
    title="PDAC organoids and cell lines",
    summary="Patient-derived organoids from adult donors.",
    overall_design="Tumor and normal organoids; two cell lines.",
    samples=[
        *(sample(f"GSM{i}", f"PDO{i}_T", "cell type: organoid", "tissue: tumor", f"age: {40 + i}")
          for i in (1, 2, 3)),
        *(sample(f"GSM{i}", f"PDO{i}_N", "cell type: organoid", "tissue: normal", f"age: {40 + i}")
          for i in (4, 5, 6)),
        sample("GSM7", "PANC1_a", "cell type: cell line", "tissue: tumor",
               growth_protocol="Cells were grown in DMEM " + "x" * 400),
        sample("GSM8", "PANC1_b", "cell type: cell line", "tissue: tumor"),
        sample("GSM9", "mouse_1", "cell type: organoid", "tissue: tumor", organism="Mus musculus"),
    ],
)  # fmt: skip


def rule(**fields: list[str]) -> Rule:
    return Rule(all_of=[Condition(field=k.replace("_", " "), equals=v) for k, v in fields.items()])


def test_digest_groups_values_and_counts_samples() -> None:
    text = series_digest(ORGANOIDS, columns=["GSM1", "GSM2", "GSM4"])
    assert "9 samples; 3 in the NCBI count table" in text
    assert '- cell type (2 values): "organoid" x7 | "cell line" x2' in text
    assert '"PDO1_T" | "PDO2_T"' in text  # titles listed, one per sample
    assert "age (6 values" in text and "numbers 41 to 46" in text
    assert "Organisms (only human samples can be selected): Mus musculus x1" in text
    assert "…" in text  # the long protocol is cut


def test_rules_choose_arms_and_leave_the_rest_out() -> None:
    sel = select_samples(
        ORGANOIDS,
        case=[rule(cell_type=["organoid"], tissue=["tumor"])],
        control=[rule(cell_type=["organoid"], tissue=["normal"])],
        columns=["GSM1", "GSM2", "GSM4", "GSM5", "GSM6", "GSM7"],
    )
    assert sel.case_gsms == ["GSM1", "GSM2", "GSM3"]
    assert sel.control_gsms == ["GSM4", "GSM5", "GSM6"]
    # cell lines, and the mouse organoid despite matching the case rule
    assert sel.excluded_gsms == ["GSM7", "GSM8", "GSM9"]
    assert sel.no_counts_gsms == ["GSM3"] and sel.counts_checked
    assert sel.analysable("case") == ["GSM1", "GSM2"]
    assert sel.problems == []
    assert sel.case_rule == 'cell type = "organoid" and tissue = "tumor"'


def test_contains_numbers_series_quotes_and_unclear() -> None:
    sel = select_samples(
        ORGANOIDS,
        case=[Rule(all_of=[Condition(field="title", contains=["_t"]),
                           Condition(field="age", min=42)])],
        control=[Rule(all_of=[Condition(field="series", contains=["ADULT DONORS"]),
                              Condition(field="tissue", equals=["normal"])])],
        unclear=[Rule(all_of=[Condition(field="growth_protocol", contains=["dmem"])])],
    )  # fmt: skip
    assert sel.case_gsms == ["GSM2", "GSM3"]  # GSM1 is 41
    assert sel.control_gsms == ["GSM4", "GSM5", "GSM6"]
    assert sel.unclear_gsms == ["GSM7"]
    assert not sel.counts_checked and sel.no_counts_gsms == []


def test_values_not_in_the_record_match_nothing_and_are_reported() -> None:
    sel = select_samples(
        ORGANOIDS,
        case=[rule(cell_type=["Organoid"])],  # wrong case: not verbatim
        control=[rule(genotype=["WT"])],
        unclear=[Rule(all_of=[Condition(field="series", contains=["children"])])],
    )
    assert sel.case_gsms == sel.control_gsms == sel.unclear_gsms == []
    assert sel.problems == [
        "case: cell type has no value ['Organoid']",
        "control: no sample field 'genotype'",
        "unclear: series text does not contain ['children']",
    ]


def test_a_sample_in_both_arms_is_set_aside() -> None:
    sel = select_samples(
        ORGANOIDS, case=[rule(cell_type=["organoid"])], control=[rule(tissue=["normal"])]
    )
    assert sel.control_gsms == []
    assert sel.unclear_gsms == ["GSM4", "GSM5", "GSM6"]
    assert sel.problems[-1].startswith("3 samples matched both arms")


def test_sample_fields_skip_empty_values() -> None:
    s = sample("GSM1", "t", "a: 1", "a: 2", source_name="blood")
    assert sample_fields(s) == {"title": "t", "source_name": "blood", "a": "1", "a.2": "2"}


# ---------------------------------------------------------------- discover end to end


def soft_text(series: GeoSeries) -> str:
    lines = [
        f"^SERIES = {series.gse}",
        f"!Series_title = {series.title}",
        f"!Series_summary = {series.summary}",
    ]
    for s in series.samples:
        lines += [
            f"^SAMPLE = {s.gsm}",
            f"!Sample_title = {s.title}",
            f"!Sample_organism_ch1 = {s.organism or 'Homo sapiens'}",
        ]
        lines += [f"!Sample_characteristics_ch1 = {c}" for c in s.characteristics]
    return "\n".join(lines) + "\n"  # fmt: skip


SMALL = GeoSeries(
    gse="GSE250219",
    title="small",
    samples=[
        sample("GSM21", "a", "tissue: tumor"),
        sample("GSM22", "b", "tissue: tumor"),
        sample("GSM23", "c", "tissue: normal"),
        sample("GSM24", "d", "tissue: normal"),
    ],
)


def geo_with_records() -> httpx.MockTransport:
    import gzip

    files = {
        soft_url("GSE164073"): gzip.compress(soft_text(ORGANOIDS).encode()),
        counts_url("GSE164073"): gzip.compress(
            b"GeneID\tGSM1\tGSM2\tGSM3\tGSM4\tGSM5\tGSM6\tGSM9\n"
        ),
        soft_url("GSE250219"): gzip.compress(soft_text(SMALL).encode()),
        counts_url("GSE250219"): gzip.compress(b"GeneID\tGSM21\tGSM22\tGSM23\tGSM24\n"),
    }  # fmt: skip

    def handle(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.url.path.endswith("esearch.fcgi"):
            ids = ["200164073", "200250219"]
            return httpx.Response(200, json={"esearchresult": {"count": "2", "idlist": ids}})
        if request.url.path.endswith("esummary.fcgi"):
            return httpx.Response(200, json=ESUMMARY)
        return httpx.Response(200, content=files[url]) if url in files else httpx.Response(404)

    return httpx.MockTransport(handle)


def candidate(gse: str, case: Rule, control: Rule) -> dict[str, Any]:
    return {
        "gse": gse,
        "title": "t",
        "n_samples": 6,
        "why": "fits",
        "case_hint": "tumor organoids",
        "control_hint": "normal organoids",
        "case": [case.model_dump()],
        "control": [control.model_dump()],
    }


async def test_discover_inspects_selects_and_demotes_thin_series() -> None:
    final = DiscoveryOutput.model_validate(
        {
            "interpretation": "PDAC tumor vs normal organoids",
            "candidates": [
                candidate("GSE164073", rule(cell_type=["organoid"], tissue=["tumor"]),
                          rule(cell_type=["organoid"], tissue=["normal"])),
                candidate("GSE250219", rule(tissue=["tumor"]), rule(tissue=["normal"])),
            ],
        }
    )  # fmt: skip
    turns = ScriptedTurns(
        message(
            [
                {
                    "type": "tool_use",
                    "id": "tu_1",
                    "name": "search_geo",
                    "input": {"queries": ["PDAC organoid"], "since": None},
                },
                {
                    "type": "tool_use",
                    "id": "tu_2",
                    "name": "inspect_series",
                    "input": {"gses": ["GSE164073", "gse250219", "GSE404", "not one"]},
                },
            ],
            stop="tool_use",
        ),
        message([{"type": "text", "text": final.model_dump_json()}]),
    )
    async with httpx.AsyncClient(transport=geo_with_records()) as http:
        result = await Discoverer(GeoClient(http), turn=turns).discover("PDAC organoids", quiet)

    _, inspect = result.trace.calls
    assert inspect.tool == "inspect_series" and inspect.inspected == ["GSE164073", "GSE250219"]
    shown = turns.requests[1]["messages"][-1]["content"][1]["content"]
    assert '- cell type (2 values): "organoid" x7' in shown
    assert "GSE404: the GEO record could not be read" in shown
    # GSE250219 has only two samples per arm: code sets it aside, whatever the model said.
    assert [c.gse for c in result.candidates] == ["GSE164073"]
    assert result.rejected[-1].gse == "GSE250219" and "case 2, control 2" in result.rejected[-1].why
    first, thin = result.selections
    assert first.case_gsms == ["GSM1", "GSM2", "GSM3"]
    assert first.control_gsms == ["GSM4", "GSM5", "GSM6"]
    assert first.no_counts_gsms == [] and first.counts_checked
    assert first.excluded_gsms == ["GSM7", "GSM8", "GSM9"]
    assert result.candidates[0].concerns == []
    assert thin.gse == "GSE250219"
    # Claude is told about the rules in its schema.
    schema = turns.requests[0]["output_config"]["format"]["schema"]
    assert "case" in str(schema) and "all_of" in str(schema)
