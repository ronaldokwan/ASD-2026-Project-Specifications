"""Student 5 - frontend microservice tests (HTMX partials).

The backend/API microservice is stubbed, so these tests verify the rendered
HTML and the HTMX wiring rather than the API itself.
"""

import api_client


def test_index_renders_the_reviews(frontend, fake_api):
    html = frontend.get("/").get_data(as_text=True)
    assert "Reviews and Ratings" in html
    assert "Fantastic noise cancelling" in html
    assert "/shared/css/theme.css" in html          # shared team theme
    assert 'id="review-form"' in html
    assert 'id="ai-panel"' in html


def test_reviews_partial_is_a_fragment(frontend, fake_api):
    html = frontend.get("/partials/reviews?product_sku=SKU-AUD-1001").get_data(as_text=True)
    assert "<html" not in html
    assert 'id="review-table"' in html


def test_create_returns_alert_plus_out_of_band_swaps(frontend, fake_api):
    html = frontend.post("/reviews", data={
        "product_sku": "SKU-AUD-1001", "user_id": "new-user", "rating": "5",
        "review": "Would recommend to anyone.",
    }).get_data(as_text=True)

    assert fake_api["created"][0]["product_sku"] == "SKU-AUD-1001"
    assert 'class="alert ok"' in html
    assert 'hx-swap-oob="true"' in html            # table + form refresh in place


def test_validation_errors_are_shown_in_the_form(frontend, fake_api, monkeypatch):
    def boom(_payload):
        raise api_client.ApiError("validation failed", 400, ["review must be between 5 and 1000 characters"])

    monkeypatch.setattr(api_client, "create_review", boom)

    html = frontend.post("/reviews", data={
        "product_sku": "SKU-AUD-1001", "user_id": "new-user", "rating": "5", "review": "hi",
    }).get_data(as_text=True)
    assert "review must be between" in html
    assert 'class="alert error"' in html


def test_edit_form_is_prefilled(frontend, fake_api):
    html = frontend.get("/partials/form/r1").get_data(as_text=True)
    assert "Editing review" in html
    assert 'hx-post="/reviews/r1"' in html


def test_delete_reports_success(frontend, fake_api):
    html = frontend.post("/reviews/r1/delete").get_data(as_text=True)
    assert fake_api["deleted"] == ["r1"]
    assert "deleted" in html


def test_ai_panel_requires_a_product(frontend, fake_api):
    html = frontend.post("/ai/summary", data={"product_sku": ""}).get_data(as_text=True)
    assert "Choose a product" in html


def test_ai_panel_renders_result_and_trace(frontend, fake_api, monkeypatch):
    monkeypatch.setattr(api_client, "generate_summary", lambda product_sku: {
        "ok": True,
        "result": {
            "summary": "Reviewers love the sound quality but a few dislike the fit.",
            "pros": "great sound; long battery life",
            "cons": "headband can pinch",
        },
        "attempts": 2,
        "fallback_used": False,
        "model": "qwen2.5:0.5b",
        "elapsed_ms": 1500,
        "trace": [
            {"step": "Plan", "attempt": 1, "detail": "Built a grounded prompt."},
            {"step": "Act", "attempt": 1, "detail": "Called the LLM."},
            {"step": "Observe", "attempt": 1, "status": "failed", "detail": "Summary too short."},
            {"step": "Adapt", "attempt": 2, "detail": "Re-prompted with the violation."},
        ],
        "grounding": {"review_count": 2},
    })

    html = frontend.post("/ai/summary", data={"product_sku": "SKU-AUD-1001"}).get_data(as_text=True)
    assert "Reviewers love the sound quality" in html
    assert "great sound" in html
    assert "headband can pinch" in html
    for step in ("Plan", "Act", "Observe", "Adapt"):
        assert step in html


def test_ai_panel_shows_fallback_warning(frontend, fake_api, monkeypatch):
    monkeypatch.setattr(api_client, "generate_summary", lambda product_sku: {
        "ok": True,
        "result": {"summary": "Locally generated summary.", "pros": "Not enough data yet.",
                   "cons": "Not enough data yet."},
        "attempts": 2,
        "fallback_used": True,
        "error": "output was not valid JSON",
        "model": "qwen2.5:0.5b",
        "elapsed_ms": 300,
        "trace": [{"step": "Adapt", "status": "fallback", "detail": "Used the fallback."}],
    })

    html = frontend.post("/ai/summary", data={"product_sku": "SKU-AUD-1001"}).get_data(as_text=True)
    assert "local fallback was used" in html


def test_backend_outage_is_reported_on_the_page(frontend, monkeypatch):
    def boom(**_kwargs):
        raise api_client.ApiError("Reviews and Ratings API is unreachable.", 503)

    monkeypatch.setattr(api_client, "list_reviews", boom)
    monkeypatch.setattr(api_client, "list_products", lambda: [])

    html = frontend.get("/").get_data(as_text=True)
    assert "unreachable" in html
