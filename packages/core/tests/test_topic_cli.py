from unittest.mock import AsyncMock

import pytest

from cell_ledger import topic_cli


@pytest.mark.parametrize("prefixed", [False, True])
def test_cli_credential_aliases_and_precedence(tmp_path, monkeypatch, prefixed):
    monkeypatch.setattr(topic_cli, "load_dotenv", lambda: None)
    for name in ("ANTHROPIC_API_KEY", "NCBI_API_KEY"):
        monkeypatch.setenv(name, "fallback")
        monkeypatch.delenv(f"CELL_LEDGER_{name}", raising=False)
        if prefixed:
            monkeypatch.setenv(f"CELL_LEDGER_{name}", "preferred")
    pipeline = AsyncMock(return_value={"status": "complete"})
    monkeypatch.setattr(topic_cli, "run_pipeline", pipeline)
    topic_cli.main(["human study", "--out", str(tmp_path / "run"), "--model", "test-model"])
    call = pipeline.call_args
    expected = "preferred" if prefixed else "fallback"
    assert call.args[2].api_key == expected
    assert call.kwargs["interpreter"].api_key == expected
