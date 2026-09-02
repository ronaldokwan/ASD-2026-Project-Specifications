"""Student 4 - frontend microservice tests (HTMX partials).

The backend/API microservice is stubbed, so these tests verify the rendered
HTML and the HTMX wiring rather than the API itself.
"""

import api_client


def test_index_renders_the_catalogue(frontend, fake_api):
    html = frontend.get("/").get_data(as_text=True)
    assert "Product Catalogue" in html
    assert "Aurora Wireless Headphones" in html
    assert "/shared/css/theme.css" in html          # shared team theme
    assert 'id="product-form"' in html
    assert 'id="ai-panel"' in html


def test_products_partial_is_a_fragment(frontend, fake_api):
    html = frontend.get("/partials/products?category=Audio").get_data(as_text=True)
    assert "<html" not in html
    assert 'id="product-table"' in html


def test_create_returns_alert_plus_out_of_band_swaps(frontend, fake_api):
    html = frontend.post("/products", data={
        "sku": "SKU-NEW-1", "name": "New Product", "category": "Audio",
        "price": "59.99", "description": "Fresh stock.", "status": "active",
    }).get_data(as_text=True)

    assert fake_api["created"][0]["sku"] == "SKU-NEW-1"
    assert 'class="alert ok"' in html
    assert 'hx-swap-oob="true"' in html            # table + form refresh in place


def test_validation_errors_are_shown_in_the_form(frontend, fake_api, monkeypatch):
    def boom(_payload):
        raise api_client.ApiError("validation failed", 400, ["sku is required"])

    monkeypatch.setattr(api_client, "create_product", boom)

    html = frontend.post("/products", data={"name": "No SKU", "category": "Audio",
                                            "price": "10"}).get_data(as_text=True)
    assert "sku is required" in html
    assert 'class="alert error"' in html


def test_edit_form_is_prefilled(frontend, fake_api):
    html = frontend.get("/partials/form/1").get_data(as_text=True)
    assert "Aurora Wireless Headphones" in html
    assert "Save changes" in html
    assert 'hx-post="/products/1"' in html


def test_delete_reports_success(frontend, fake_api):
    html = frontend.post("/products/1/delete").get_data(as_text=True)
    assert fake_api["deleted"] == [1]
    assert "deleted" in html


def test_ai_panel_requires_name_and_category(frontend, fake_api):
    html = frontend.post("/ai/suggest", data={"name": "", "category": ""}).get_data(as_text=True)
    assert "Enter a product name and a category" in html


def test_ai_panel_renders_result_and_trace(frontend, fake_api, monkeypatch):
    monkeypatch.setattr(api_client, "generate_copy", lambda name, category, keywords="": {
        "ok": True,
        "result": {"description": "Comfortable headphones for daily commuting.", "price": 179.0},
        "attempts": 2,
        "fallback_used": False,
        "model": "qwen2.5:0.5b",
        "elapsed_ms": 1500,
        "trace": [
            {"step": "Plan", "attempt": 1, "detail": "Built a grounded prompt."},
            {"step": "Act", "attempt": 1, "detail": "Called the LLM."},
            {"step": "Observe", "attempt": 1, "status": "failed", "detail": "Price too high."},
            {"step": "Adapt", "attempt": 2, "detail": "Re-prompted with the violation."},
        ],
        "grounding": {"category_avg_price": 199.95},
    })

    html = frontend.post("/ai/suggest", data={"name": "Aurora Headphones",
                                              "category": "Audio"}).get_data(as_text=True)
    assert "Comfortable headphones" in html
    assert "179.00" in html
    for step in ("Plan", "Act", "Observe", "Adapt"):
        assert step in html
    assert "data-apply-ai" in html                 # human reviews before saving


def test_ai_panel_shows_fallback_warning(frontend, fake_api, monkeypatch):
    monkeypatch.setattr(api_client, "generate_copy", lambda name, category, keywords="": {
        "ok": True,
        "result": {"description": "Locally generated copy.", "price": 49.95},
        "attempts": 2,
        "fallback_used": True,
        "error": "output was not valid JSON",
        "model": "qwen2.5:0.5b",
        "elapsed_ms": 300,
        "trace": [{"step": "Adapt", "status": "fallback", "detail": "Used the fallback."}],
    })

    html = frontend.post("/ai/suggest", data={"name": "Widget",
                                              "category": "Audio"}).get_data(as_text=True)
    assert "local fallback was used" in html


def test_backend_outage_is_reported_on_the_page(frontend, monkeypatch):
    def boom(**_kwargs):
        raise api_client.ApiError("Product Catalogue API is unreachable.", 503)

    monkeypatch.setattr(api_client, "list_products", boom)
    monkeypatch.setattr(api_client, "list_categories", lambda: [])

    html = frontend.get("/").get_data(as_text=True)
    assert "unreachable" in html
