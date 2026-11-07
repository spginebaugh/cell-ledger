import json

import httpx
import pytest

from cell_ledger.geo.models import GeoError
from cell_ledger.interpretation import Interpreter, SearchPlan


@pytest.mark.parametrize("valid", [True, False])
async def test_auto_tool_choice_still_requires_structured_result(tmp_path, monkeypatch, valid):
    real_client = httpx.AsyncClient

    def respond(request):
        body = json.loads(request.content)
        if body["tool_choice"]["type"] in {"tool", "any"}:
            return httpx.Response(400, json={"error": "Forced tools unsupported"})
        content: list[dict[str, object]] = [{"type": "thinking", "thinking": ""}]
        if valid:
            content.append(
                {
                    "type": "tool_use",
                    "name": "submit",
                    "input": {"queries": ["human macrophages"]},
                }
            )
        else:
            content.append({"type": "text", "text": "human macrophages"})
        return httpx.Response(200, json={"content": content, "stop_reason": "end_turn"})

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    interpreter = Interpreter("claude-opus-5-5", "test-only", tmp_path)
    if valid:
        result = await interpreter.extract("Plan queries", {"topic": "macrophages"}, SearchPlan)
        assert result.queries == ["human macrophages"]
        assert len(list(tmp_path.glob("*.json"))) == 1
    else:
        with pytest.raises(GeoError, match="complete structured interpretation"):
            await interpreter.extract("Plan queries", {"topic": "macrophages"}, SearchPlan)
        assert not list(tmp_path.glob("*.json"))


async def test_sample_batches_repair_missing_ids_and_keep_ineligible_records(tmp_path):
    from cell_ledger.geo.models import GeoSample, GeoSeries
    from cell_ledger.interpretation import LabelResponse

    samples = [
        GeoSample(
            gsm=f"GSM{i}",
            fields={
                "organism_ch1": ["Homo sapiens"],
                "library_strategy": ["RNA-Seq"],
                "characteristics_ch1": ["treatment: IFNG"],
            },
        )
        for i in range(1, 10)
    ]
    samples.append(GeoSample(gsm="GSM10", fields={"organism_ch1": ["Mus musculus"]}))
    series = GeoSeries(
        gse="GSE1",
        source_url="https://example.org",
        samples=samples,
        fields={"sample_id": [s.gsm for s in samples]},
    )
    calls = []

    class MissingIDs(Interpreter):
        async def extract(self, task, data, schema):
            batch = data["series"]["samples"]
            calls.append([s["gsm"] for s in batch])
            assert len(batch) <= 4
            assert "sample_id" not in data["series"]["fields"]
            assert all(s["gsm"] != "GSM10" for s in batch)
            # Simulate a model dropping one entry until we retry smaller batches.
            chosen = batch if len(batch) == 1 else batch[:-1]
            return LabelResponse.model_validate(
                {
                    "samples": [
                        {
                            "gsm": s["gsm"],
                            "labels": {
                                "group": {
                                    "value": "case",
                                    "evidence": "treatment: IFNG",
                                    "source_field": "characteristics_ch1",
                                    "confidence": 1,
                                }
                            },
                        }
                        for s in chosen
                    ]
                }
            )

    result = await MissingIDs("test", "test", tmp_path).label_samples("IFNG", series)
    assert [s.gsm for s in result] == [s.gsm for s in samples]
    assert all(s.group == "case" for s in result[:-1])
    assert result[-1].group == "unknown"
    assert any(len(batch) == 1 for batch in calls)


async def test_wrong_single_sample_id_is_rejected(tmp_path):
    from cell_ledger.geo.models import GeoSample, GeoSeries
    from cell_ledger.interpretation import LabelResponse

    class WrongID(Interpreter):
        async def extract(self, task, data, schema):
            return LabelResponse.model_validate({"samples": [{"gsm": "GSM999", "labels": {}}]})

    sample = GeoSample(
        gsm="GSM1", fields={"organism_ch1": ["Homo sapiens"], "library_strategy": ["RNA-Seq"]}
    )
    with pytest.raises(GeoError, match="requested GSMs"):
        await WrongID("test", "test", tmp_path).label_samples(
            "IFNG", GeoSeries(gse="GSE1", source_url="https://example.org", samples=[sample])
        )
