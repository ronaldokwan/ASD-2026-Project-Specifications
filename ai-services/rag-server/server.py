"""Optional MCP stdio exposure of the shared RAG pipeline.

Student backends use the native RAG HTTP API on port 7003. This process is for
MCP-aware local clients and uses the same validated pipeline functions.
"""

from typing import Any

from mcp.server.mcpserver import MCPServer

from rag_pipeline import (
    answer_question,
    delete_document,
    retrieve_context,
    upsert_documents,
)

mcp = MCPServer("ASD Group 40 Shared RAG Server", version="1.1.0")

AVAILABLE_TOOLS = [
    "upsert_documents", "delete_document", "retrieve_context", "answer_question"
]


@mcp.tool(name="upsert_documents", structured_output=True)
def upsert_documents_tool(documents: list[dict[str, Any]]) -> dict[str, Any]:
    return upsert_documents(documents)


@mcp.tool(name="delete_document", structured_output=True)
def delete_document_tool(doc_id: str) -> dict[str, Any]:
    return delete_document(doc_id)


@mcp.tool(name="retrieve_context", structured_output=True)
def retrieve_context_tool(
    query: str, top_k: int = 5, filters: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    return retrieve_context(query, top_k=top_k, filters=filters)


@mcp.tool(name="answer_question", structured_output=True)
def answer_question_tool(
    query: str, top_k: int = 5, filters: dict[str, Any] | None = None
) -> dict[str, Any]:
    return answer_question(query, top_k=top_k, filters=filters)


if __name__ == "__main__":
    mcp.run(transport="stdio")
