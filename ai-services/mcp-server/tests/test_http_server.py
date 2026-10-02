"""HTTP-layer tests for the shared MCP server's Flask front door.

Run from the repository root:  pytest ai-services/mcp-server/tests -v
"""

import os
import sys

SERVICE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SERVICE_ROOT)

from http_server import app  # noqa: E402


def client():
    app.config.update(TESTING=True)
    return app.test_client()


def test_health():
    res = client().get("/health")
    assert res.status_code == 200
    assert res.get_json()["status"] == "ok"


def test_list_tools():
    res = client().get("/tools")
    assert res.status_code == 200
    assert "check_review_quality" in res.get_json()["tools"]
    assert "check_order_fulfilment" in res.get_json()["tools"]


def test_run_check_review_quality():
    res = client().post("/tools/check_review_quality", json={
        "review_text": "Battery life is excellent and it charges fast.",
        "rating": 5,
        "existing_review_count": 4,
        "average_rating": 4.2,
    })
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    assert body["result"]["flagged"] is False


def test_missing_required_fields_returns_400():
    res = client().post("/tools/check_review_quality", json={"rating": 5})
    assert res.status_code == 400


def test_run_check_order_fulfilment():
    res = client().post("/tools/check_order_fulfilment", json={
        "order_number": "ORD-100",
        "status": "pending",
        "line_count": 2,
        "total_quantity": 3,
        "order_total": 89.90,
        "inventory_committed": True,
    })
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    assert body["tool"] == "check_order_fulfilment"
    assert body["result"]["ready_to_ship"] is True


def test_order_fulfilment_requires_all_grounding_fields():
    res = client().post("/tools/check_order_fulfilment", json={"order_number": "ORD-100"})
    assert res.status_code == 400
    assert "status" in res.get_json()["error"]


def test_unknown_route_returns_404():
    res = client().post("/tools/does_not_exist", json={})
    assert res.status_code == 404
