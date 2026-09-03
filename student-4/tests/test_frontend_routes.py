"""Student 4 - frontend microservice tests (HTMX partials).

The backend/API microservice is stubbed, so these tests verify the rendered
HTML and the HTMX wiring rather than the API itself.
"""

import api_client


# The page shell includes the stock dashboard, shared theme, form, and AI region.
def test_index_renders_inventory_dashboard(frontend, fake_api):
    html = frontend.get("/").get_data(as_text=True)
    assert "Stock Inventory" in html
    assert "Aurora Wireless Headphones" in html
    assert "/shared/css/theme.css" in html
    assert 'id="product-form"' in html
    assert 'id="ai-panel"' in html


# HTMX table refreshes return fragments rather than a complete HTML document.
def test_stock_partial_is_a_fragment(frontend, fake_api):
    html = frontend.get("/partials/products?category=Audio").get_data(as_text=True)
    assert "<html" not in html
    assert 'id="product-table"' in html


# Successful writes update the alert, table, and form without a full page reload.
def test_create_returns_alert_plus_out_of_band_swaps(frontend, fake_api):
    html = frontend.post("/stock", data={
        "sku": "SKU-NEW-1",
        "name": "New Widget",
        "category": "Audio",
        "location": "Shelf A4",
        "quantity": "12",
        "restock_threshold": "20",
        "stock_level": "low",
    }).get_data(as_text=True)

    assert fake_api["created"][0]["sku"] == "SKU-NEW-1"
    assert 'class="alert ok"' in html
    assert 'hx-swap-oob="true"' in html


# API validation details are returned in the form the user submitted.
def test_validation_errors_are_shown_in_the_form(frontend, fake_api, monkeypatch):
    def boom(_payload):
        raise api_client.ApiError("validation failed", 400, ["quantity is required"])

    monkeypatch.setattr(api_client, "create_stock", boom)

    html = frontend.post("/stock", data={
        "sku": "SKU-NEW-1",
        "name": "No Quantity",
        "category": "Audio",
        "location": "Shelf A4",
        "restock_threshold": "20",
    }).get_data(as_text=True)
    assert "quantity is required" in html
    assert 'class="alert error"' in html


# Selecting Edit fetches the item and configures the form for an update request.
def test_edit_form_is_prefilled(frontend, fake_api):
    html = frontend.get("/partials/form/1").get_data(as_text=True)
    assert "Aurora Wireless Headphones" in html
    assert "Save changes" in html
    assert 'hx-post="/stock/1"' in html
    assert "location" in html


# Deleting through HTMX calls the stock API and returns a confirmation fragment.
def test_delete_reports_success(frontend, fake_api):
    html = frontend.post("/stock/1/delete").get_data(as_text=True)
    assert fake_api["deleted"] == [1]
    assert "deleted" in html


# AI restock advice requires a category to ground its recommendation.
def test_ai_panel_requires_name_and_category(frontend, fake_api):
    html = frontend.post("/ai/recommend", data={"category": ""}).get_data(as_text=True)
    assert "Enter a category" in html


# The UI renders AI recommendations and the Plan/Act/Observe/Adapt trace.
def test_ai_panel_renders_restock_recommendation(frontend, fake_api, monkeypatch):
    monkeypatch.setattr(api_client, "generate_recommendation", lambda category: {
        "ok": True,
        "result": {"recommendations": [
            {"sku": "SKU-AUD-1001", "order_quantity": 30, "reason": "Inventory is below threshold."}
        ]},
        "attempts": 2,
        "fallback_used": False,
        "model": "qwen2.5:0.5b",
        "elapsed_ms": 1500,
        "trace": [
            {"step": "Plan", "attempt": 1, "detail": "Reviewed low stock."},
            {"step": "Act", "attempt": 1, "detail": "Asked the model for a restock plan."},
            {"step": "Observe", "attempt": 1, "status": "passed", "detail": "Recommendation valid."},
            {"step": "Adapt", "attempt": 2, "detail": "Refined quantity."},
        ],
        "grounding": {"low_stock_count": 1},
    })

    html = frontend.post("/ai/recommend", data={"category": "Audio"}).get_data(as_text=True)
    assert "SKU-AUD-1001" in html
    assert "30" in html
    for step in ("Plan", "Act", "Observe", "Adapt"):
        assert step in html
    assert "data-apply-ai" in html


# A backend outage is visible to the user rather than breaking page rendering.
def test_backend_outage_is_reported_on_the_page(frontend, monkeypatch):
    def boom(**_kwargs):
        raise api_client.ApiError("Inventory and Stock API is unreachable.", 503)

    monkeypatch.setattr(api_client, "list_stock", boom)
    monkeypatch.setattr(api_client, "list_categories", lambda: [])

    html = frontend.get("/").get_data(as_text=True)
    assert "unreachable" in html
