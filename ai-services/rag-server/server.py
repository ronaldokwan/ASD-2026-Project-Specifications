"""The shared RAG server's MCP front door (real Model Context Protocol, stdio).

Mirrors ``ai-services/mcp-server/server.py``: any MCP-aware client can list
and call these tools directly via ``mcp-config.json``. Student backends
instead call ``http_server.py`` over plain HTTP within a request/response
cycle - both front doors call the same functions in ``rag_pipeline.py``.

Run standalone:  python server.py
"""

from mcp.server.fastmcp import FastMCP

from rag_pipeline import answer_question, delete_document, retrieve_context, upsert_documents

mcp = FastMCP("ASD Group 40 Shared RAG Server")

AVAILABLE_TOOLS = ["upsert_documents", "delete_document", "retrieve_context", "answer_question"]


@mcp.tool()
def upsert_documents_tool(documents: list):
    return upsert_documents(documents)


@mcp.tool()
def delete_document_tool(doc_id: str):
    return delete_document(doc_id)


@mcp.tool()
def retrieve_context_tool(query: str, top_k: int = 5):
    return retrieve_context(query, top_k=top_k)


@mcp.tool()
def answer_question_tool(query: str, top_k: int = 5):
    return answer_question(query, top_k=top_k)


if __name__ == "__main__":
    print("Starting the shared RAG server (Group 40)...")
    print("Server status: RUNNING")
    print("Available tools:")
    for tool in AVAILABLE_TOOLS:
        print("- {}".format(tool))
    mcp.run()
