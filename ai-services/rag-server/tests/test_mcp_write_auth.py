"""The stdio MCP tools enforce the same shared write credential as HTTP."""

import os
import sys

import pytest

SERVICE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SERVICE_ROOT)

import server  # noqa: E402


TEST_AUTH_VALUE = "test-rag-service-token"


@pytest.mark.parametrize("operation", ["upsert", "delete"])
def test_mcp_write_tools_reject_wrong_credential(monkeypatch, operation):
    monkeypatch.setenv("RAG_SERVICE_TOKEN", TEST_AUTH_VALUE)
    monkeypatch.setattr(
        server,
        "upsert_documents" if operation == "upsert" else "delete_document",
        lambda *_args: pytest.fail("write reached pipeline"),
    )

    with pytest.raises(ValueError, match="credential"):
        if operation == "upsert":
            server.upsert_documents_tool([], "wrong")
        else:
            server.delete_document_tool("r1", "wrong")


def test_mcp_write_tool_accepts_configured_credential(monkeypatch):
    monkeypatch.setenv("RAG_SERVICE_TOKEN", TEST_AUTH_VALUE)
    monkeypatch.setattr(server, "upsert_documents", lambda documents: {"ok": bool(documents)})

    assert server.upsert_documents_tool([{"id": "r1"}], TEST_AUTH_VALUE) == {"ok": True}
