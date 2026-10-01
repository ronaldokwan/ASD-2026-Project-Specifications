import asyncio
import json
import os
import sys
import time
from pathlib import Path

import requests
from mcp import Client

REPO = Path(__file__).resolve().parents[2]
OUT = Path(os.getenv("EVIDENCE_DIR", REPO / "docs" / "evidence" / "student-1"))

MCP_URL = os.getenv("MCP_URL", "http://localhost:7002")
RAG_URL = os.getenv("RAG_URL", "http://localhost:7003")
AI_MODE_URL = os.getenv("AI_MODE_URL", "http://localhost:7001")
BACKEND = os.getenv("BACKEND_URL", "http://localhost:8001")
FRONTEND = os.getenv("FRONTEND_URL", "http://localhost:3001")
LLM_WAIT = 300

GROUNDED_QUESTION = "Which headphones have active noise cancelling?"
POLICY_QUESTION = "What price range is allowed for a catalogue product?"
OFF_TOPIC_QUESTION = "Who won the 2022 football world cup final?"

results = []


def save(name, body):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    if isinstance(body, str):
        path.write_text(body, encoding="utf-8")
    else:
        path.write_text(json.dumps(body, indent=2), encoding="utf-8")
    return path.relative_to(REPO).as_posix()


def check(label, passed, detail=""):
    results.append((label, bool(passed)))
    print(
        "  [{}] {}{}".format(
            "PASS" if passed else "FAIL", label, " - " + detail if detail else ""
        )
    )


def post(url, payload=None, form=None, timeout=LLM_WAIT):
    started = time.time()
    response = requests.post(url, json=payload, data=form, timeout=timeout)
    return response, int((time.time() - started) * 1000)


def section(title):
    print("\n== {} ==".format(title))


# ---------------------------------------------------------------- terminal
async def mcp_direct():
    async with Client("{}/mcp".format(MCP_URL)) as client:
        tools = await client.list_tools()
        names = [tool.name for tool in tools.tools]
        response = await client.call_tool(
            "check_product_listing",
            {
                "sku": "SKU-AUD-1001",
                "name": "Aurora Wireless Headphones",
                "category": "Audio",
                "price": 199.95,
                "status": "active",
                "description": "Over-ear Bluetooth headphones with active noise "
                "cancelling and a 30 hour battery.",
                "comparable_count": 2,
                "comparable_avg_price": 102.0,
                "comparable_min_price": 59.0,
                "comparable_max_price": 145.0,
            },
        )
        rejected = await client.call_tool(
            "check_product_listing",
            {
                "sku": "SKU-AUD-1001",
                "name": "Aurora",
                "category": "Audio",
                "status": "active",
                "price": "not-a-number",
            },
        )
        return names, response, rejected


def terminal_checks():
    section("1. Terminal validation of the shared MCP and RAG servers")
    health = requests.get("{}/health".format(MCP_URL), timeout=10).json()
    save("01-mcp-health.json", health)
    check(
        "MCP server is healthy",
        health.get("status") == "ok",
        health.get("protocol", ""),
    )

    names, response, rejected = asyncio.run(mcp_direct())
    save(
        "02-mcp-direct-call.json",
        {
            "endpoint": "{}/mcp".format(MCP_URL),
            "tools/list": names,
            "tools/call check_product_listing": response.structured_content,
            "is_error": response.is_error,
            "out-of-contract call is_error": rejected.is_error,
        },
    )
    check(
        "check_product_listing is registered",
        "check_product_listing" in names,
        ", ".join(names),
    )
    check(
        "tool returns a structured result",
        not response.is_error
        and response.structured_content["tool"] == "check_product_listing",
        "listing_status={}".format(response.structured_content.get("listing_status")),
    )
    check("tool boundary rejects out-of-contract arguments", rejected.is_error is True)

    health = requests.get("{}/health".format(RAG_URL), timeout=10).json()
    save("03-rag-health.json", health)
    check(
        "RAG server is healthy", health.get("status") == "ok", health.get("model", "")
    )

    for name, question, expected in (
        ("04-rag-direct-grounded.json", POLICY_QUESTION, "ok"),
        ("05-rag-direct-insufficient.json", OFF_TOPIC_QUESTION, "insufficient_context"),
    ):
        response, ms = post(
            "{}/rag/query".format(RAG_URL),
            {
                "query": question,
                "top_k": 5,
                "filters": {"feature": "product_catalogue"},
            },
        )
        body = response.json()
        save(name, {"query": question, "elapsed_ms": ms, "response": body})
        check(
            "RAG direct: {!r} -> {}".format(question, expected),
            body.get("status") == expected,
            "confidence={}, sources={}".format(
                body.get("confidence"), len(body.get("sources", []))
            ),
        )


# ----------------------------------------------------------------- backend
def backend_checks():
    section("2. MCP and RAG through the backend/API")
    health = requests.get("{}/health".format(BACKEND), timeout=15).json()
    save("06-backend-health.json", health)
    check(
        "backend reaches the database, AI-Mode, MCP and RAG",
        health["status"] == "ok"
        and health["mcp_server"].get("status") == "ok"
        and health["rag_server"].get("status") == "ok"
        and health["ai_mode"].get("status") == "ok",
    )

    sync = post("{}/api/catalogue/rag-sync".format(BACKEND))[0].json()
    save("07-backend-rag-sync.json", sync)
    check(
        "catalogue products indexed into the shared RAG corpus",
        sync.get("documents_indexed", 0) >= 10,
        "{} documents".format(sync.get("documents_indexed")),
    )

    response, ms = post("{}/api/products/1/mcp-check".format(BACKEND), {})
    body = response.json()
    save("08-backend-mcp-check.json", dict(body, round_trip_ms=ms))
    check(
        "backend MCP check returns the tool result",
        response.status_code == 200
        and body["result"]["tool"] == "check_product_listing",
        "{} / {}".format(
            body.get("result", {}).get("listing_status"),
            body.get("result", {}).get("price_position"),
        ),
    )
    outputs = {"mcp": body, "rag": []}

    for name, question in (
        ("09-backend-rag-product.json", GROUNDED_QUESTION),
        ("10-backend-rag-policy.json", POLICY_QUESTION),
    ):
        response, ms = post("{}/api/catalogue/ask".format(BACKEND), {"question": question})
        body = response.json()
        save(name, dict(body, round_trip_ms=ms))
        check(
            "backend RAG grounded answer: {!r}".format(question),
            response.status_code == 200
            and body.get("status") == "ok"
            and body.get("sources")
            and body.get("confidence") in ("high", "medium", "low"),
            "confidence={}, cites {}".format(
                body.get("confidence"),
                "; ".join(s["section"] for s in body.get("sources", [])),
            ),
        )
        outputs["rag"].append(body)

    response, ms = post(
        "{}/api/catalogue/ask".format(BACKEND), {"question": OFF_TOPIC_QUESTION}
    )
    body = response.json()
    save("11-backend-rag-insufficient.json", dict(body, round_trip_ms=ms))
    check(
        "backend RAG insufficient-context response",
        body.get("status") == "insufficient_context"
        and body.get("answer") == ""
        and body.get("sources") == [],
    )
    return outputs


# ------------------------------------------------------------- agentic loop
def agentic_loop_checks(outputs):
    """Run the shared agentic loop in its MCP and RAG validation modes.

    Each mode is given a real result produced above through the backend/API,
    and the loop's verdict plus its Plan -> Act -> Observe -> Adapt trace is
    saved as evidence.
    """
    section("3. Shared agentic loop - MCP and RAG validation modes")
    mcp = outputs["mcp"]
    response, ms = post("{}/agent/validate".format(AI_MODE_URL), {
        "mode": "mcp",
        "subject": {"tool": mcp["tool"], "arguments": mcp["arguments"],
                    "result": mcp["result"]},
    })
    body = response.json()
    save("19-agentic-loop-mcp-mode.json", dict(body, round_trip_ms=ms))
    check(
        "agentic loop MCP validation mode",
        response.status_code == 200 and body.get("mode") == "mcp_validation"
        and body.get("result", {}).get("valid") == "true",
        "valid={}, attempts={}, fallback_used={}".format(
            body.get("result", {}).get("valid"), body.get("attempts"),
            body.get("fallback_used")),
    )

    for name, answer in zip(
        ("20-agentic-loop-rag-mode-product.json", "21-agentic-loop-rag-mode-policy.json"),
        outputs["rag"],
    ):
        response, ms = post("{}/agent/validate".format(AI_MODE_URL), {
            "mode": "rag",
            "subject": {"query": answer.get("question"), "answer": answer.get("answer"),
                        "sources": answer.get("sources"),
                        "confidence": answer.get("confidence")},
        })
        body = response.json()
        save(name, dict(body, round_trip_ms=ms))
        check(
            "agentic loop RAG validation mode: {!r}".format(answer.get("question")),
            response.status_code == 200 and body.get("mode") == "rag_validation"
            and body.get("result", {}).get("grounded") == "true",
            "grounded={}, confidence_ok={}".format(
                body.get("result", {}).get("grounded"),
                body.get("result", {}).get("confidence_ok")),
        )


# ---------------------------------------------------------------- frontend
def frontend_checks():
    section("4. MCP and RAG through the frontend UI routes")
    page = requests.get(FRONTEND, timeout=15).text
    check(
        "catalogue page shows the MCP and RAG panels",
        'id="mcp-panel"' in page and 'hx-post="/catalogue/ask"' in page,
    )

    html = post("{}/products/1/mcp-check".format(FRONTEND), form={})[0].text
    save("12-frontend-mcp-result.html", html)
    check(
        "frontend renders the MCP tool result",
        "check_product_listing" in html and "Listing status" in html,
    )

    html = post(
        "{}/catalogue/ask".format(FRONTEND), form={"question": GROUNDED_QUESTION}
    )[0].text
    save("13-frontend-rag-grounded.html", html)
    check(
        "frontend renders a grounded answer with citations and confidence",
        'id="rag-answer"' in html
        and 'id="rag-confidence"' in html
        and "Sources" in html,
    )

    html = post(
        "{}/catalogue/ask".format(FRONTEND), form={"question": OFF_TOPIC_QUESTION}
    )[0].text
    save("14-frontend-rag-insufficient.html", html)
    check(
        "frontend renders the insufficient-context state",
        "Insufficient context." in html and 'id="rag-answer"' not in html,
    )


# ---------------------------------------------------------------- release 0
def release0_checks():
    section("5. Release 0 functionality still works")
    products = requests.get("{}/api/products".format(BACKEND), timeout=15).json()
    check(
        "catalogue lists products",
        products["count"] >= 10,
        "{} products".format(products["count"]),
    )

    created = post(
        "{}/api/products".format(BACKEND),
        {
            "name": "Release 1 Validation Earbuds",
            "category": "Audio",
            "price": 79.95,
            "description": "Temporary product created and deleted by the validation script.",
        },
    )[0]
    product = created.json()
    updated = requests.put(
        "{}/api/products/{}".format(BACKEND, product["id"]),
        json={"price": 74.95},
        timeout=15,
    )
    deleted = requests.delete(
        "{}/api/products/{}".format(BACKEND, product["id"]), timeout=15
    )
    gone = requests.get("{}/api/products/{}".format(BACKEND, product["id"]), timeout=15)
    save(
        "15-release0-crud.json",
        {
            "created": product,
            "updated": updated.json(),
            "deleted": deleted.json(),
            "get_after_delete": gone.status_code,
        },
    )
    check(
        "CRUD create -> update -> delete",
        created.status_code == 201
        and updated.json()["price"] == 74.95
        and gone.status_code == 404,
        product.get("sku", ""),
    )

    response, ms = post(
        "{}/api/products/ai".format(BACKEND),
        {
            "name": "Cadence Earbuds",
            "category": "Audio",
            "keywords": "waterproof, 8 hour battery",
        },
    )
    body = response.json()
    save("16-release0-ai-mode.json", dict(body, round_trip_ms=ms))
    check(
        "AI-Mode copy suggestion (Plan -> Act -> Observe -> Adapt)",
        response.status_code == 200 and body.get("result", {}).get("description"),
        "attempts={}, fallback_used={}".format(
            body.get("attempts"), body.get("fallback_used")
        ),
    )


def main():
    print("Student 1 - Product Catalogue - Release 1 validation")
    print("evidence -> {}".format(OUT))
    outputs = None
    steps = (
        terminal_checks,
        backend_checks,
        lambda: agentic_loop_checks(outputs),
        frontend_checks,
        release0_checks,
    )
    for step in steps:
        try:
            result = step()
            if step is backend_checks:
                outputs = result
        except Exception as exc:  # noqa: BLE001 - report and keep validating
            check(
                "{} raised {}".format(getattr(step, "__name__", "step"), type(exc).__name__),
                False,
                str(exc),
            )

    passed = sum(1 for _, ok in results if ok)
    summary = "{}/{} checks passed".format(passed, len(results))
    print("\n" + summary)
    save(
        "00-summary.json",
        {
            "summary": summary,
            "checks": [{"check": label, "passed": ok} for label, ok in results],
        },
    )
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
