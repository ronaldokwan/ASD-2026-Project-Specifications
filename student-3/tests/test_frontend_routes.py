"""Frontend routes and HTMX fragment tests."""

import api_client


def form_data(**overrides):
    data = {"name": "New Customer", "email": "new@example.test", "phone": "",
            "address": "Sydney NSW", "loyalty_tier": "Bronze", "joined_at": "2026-09-03"}
    data.update(overrides)
    return data


def test_index_renders_customers_and_shared_design(frontend, fake_api):
    html = frontend.get("/").get_data(as_text=True)
    assert "Customer Account Management" in html
    assert "Avery Brooks" in html
    assert "/shared/css/theme.css" in html
    assert 'id="customer-form"' in html
    assert "Add a customer" in html
    assert "Actions" in html
    assert 'aria-label="Suggest reward for Avery Brooks"' in html
    assert ">#1<" not in html


def test_search_partial(frontend, fake_api, monkeypatch):
    html = frontend.get("/partials/customers?search=avery").get_data(as_text=True)
    assert "<html" not in html
    assert 'id="customer-table"' in html
    assert "Avery Brooks" in html

    monkeypatch.setattr(
        api_client,
        "list_customers",
        lambda search=None: (_ for _ in ()).throw(
            api_client.ApiError("database unavailable", 503)
        ),
    )
    failed = frontend.get("/partials/customers?search=avery")
    assert failed.status_code == 503
    assert 'id="customer-table"' in failed.get_data(as_text=True)


def test_customer_detail(frontend, fake_api):
    html = frontend.get("/customers/1").get_data(as_text=True)
    assert "avery@example.test" in html
    assert "Sydney NSW" in html
    assert "Customer ID" not in html


def test_create_returns_oob_updates(frontend, fake_api):
    html = frontend.post("/customers", data=form_data()).get_data(as_text=True)
    assert fake_api["created"][0]["email"] == "new@example.test"
    assert 'class="alert ok"' in html
    assert 'hx-swap-oob="true"' in html


def test_edit_form_and_update(frontend, fake_api):
    form = frontend.get("/partials/form/1").get_data(as_text=True)
    assert "Edit customer" in form
    assert "Save changes" in form
    assert "Cancel editing" in form
    assert "Editing selected customer." in form
    assert "Editing customer #1" not in form
    assert 'hx-post="/customers/1"' in form
    updated = frontend.post("/customers/1", data=form_data(name="Updated Customer"))
    assert "Updated Customer" in updated.get_data(as_text=True)


def test_delete_action(frontend, fake_api):
    html = frontend.post("/customers/1/delete").get_data(as_text=True)
    assert fake_api["deleted"] == [1]
    assert "Customer deleted." in html
    assert "Customer #1" not in html


def test_validation_error_is_safely_rendered(frontend, fake_api, monkeypatch):
    monkeypatch.setattr(api_client, "create_customer", lambda payload: (_ for _ in ()).throw(
        api_client.ApiError("validation failed", 400, ["email is required"])))
    html = frontend.post("/customers", data=form_data(email="")).get_data(as_text=True)
    assert "email is required" in html
    assert 'class="alert error"' in html


def test_ai_reward_result_and_trace(frontend, fake_api):
    html = frontend.post("/customers/1/ai-reward").get_data(as_text=True)
    assert "10% off the next purchase" in html
    assert "Plan" in html
    assert '<details class="trace-details">' in html
    assert "Technical agent trace" in html
    assert "not stored or automatically applied" in html


def test_frontend_health(frontend, monkeypatch):
    monkeypatch.setattr(api_client, "backend_health", lambda: {"status": "ok"})
    assert frontend.get("/health").get_json()["status"] == "ok"
