"""Student 1 - frontend microservice tests (HTMX partials).

The backend/API microservice is stubbed, so these tests verify the rendered
HTML and the HTMX wiring rather than the API itself.
"""

import io
import os

import api_client

CSS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "frontend",
    "static",
    "css",
    "catalogue.css",
)


def test_index_renders_the_catalogue(frontend, fake_api):
    html = frontend.get("/").get_data(as_text=True)
    assert "Product Catalogue" in html
    assert "Aurora Wireless Headphones" in html
    assert "/shared/css/theme.css" in html  # shared team theme
    assert 'id="product-form"' in html
    assert 'id="ai-panel"' in html


def test_products_partial_is_a_fragment(frontend, fake_api):
    html = frontend.get("/partials/products?category=Audio").get_data(as_text=True)
    assert "<html" not in html
    assert 'id="product-table"' in html


def test_create_returns_alert_plus_out_of_band_swaps(frontend, fake_api):
    html = frontend.post(
        "/products",
        data={
            "sku": "SKU-NEW-1",
            "name": "New Product",
            "category": "Audio",
            "price": "59.99",
            "description": "Fresh stock.",
            "status": "active",
        },
    ).get_data(as_text=True)

    assert fake_api["created"][0]["sku"] == "SKU-NEW-1"
    assert 'class="alert ok"' in html
    assert 'hx-swap-oob="true"' in html  # table + form refresh in place


def test_validation_errors_are_shown_in_the_form(frontend, fake_api, monkeypatch):
    def boom(_payload):
        raise api_client.ApiError("validation failed", 400, ["sku is required"])

    monkeypatch.setattr(api_client, "create_product", boom)

    html = frontend.post(
        "/products", data={"name": "No SKU", "category": "Audio", "price": "10"}
    ).get_data(as_text=True)
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
    html = frontend.post("/ai/suggest", data={"name": "", "category": ""}).get_data(
        as_text=True
    )
    assert "Enter a product name and a category" in html


def test_ai_panel_renders_result_and_trace(frontend, fake_api, monkeypatch):
    monkeypatch.setattr(
        api_client,
        "generate_copy",
        lambda name, category, keywords="": {
            "ok": True,
            "result": {
                "description": "Comfortable headphones for daily commuting.",
                "price": 179.0,
            },
            "attempts": 2,
            "fallback_used": False,
            "model": "qwen2.5:0.5b",
            "elapsed_ms": 1500,
            "trace": [
                {"step": "Plan", "attempt": 1, "detail": "Built a grounded prompt."},
                {"step": "Act", "attempt": 1, "detail": "Called the LLM."},
                {
                    "step": "Observe",
                    "attempt": 1,
                    "status": "failed",
                    "detail": "Price too high.",
                },
                {
                    "step": "Adapt",
                    "attempt": 2,
                    "detail": "Re-prompted with the violation.",
                },
            ],
            "grounding": {"category_avg_price": 199.95},
        },
    )

    html = frontend.post(
        "/ai/suggest", data={"name": "Aurora Headphones", "category": "Audio"}
    ).get_data(as_text=True)
    assert "Comfortable headphones" in html
    assert "179.00" in html
    for step in ("Plan", "Act", "Observe", "Adapt"):
        assert step in html
    assert "data-apply-ai" in html  # human reviews before saving


def test_ai_panel_shows_fallback_warning(frontend, fake_api, monkeypatch):
    monkeypatch.setattr(
        api_client,
        "generate_copy",
        lambda name, category, keywords="": {
            "ok": True,
            "result": {"description": "Locally generated copy.", "price": 49.95},
            "attempts": 2,
            "fallback_used": True,
            "error": "output was not valid JSON",
            "model": "qwen2.5:0.5b",
            "elapsed_ms": 300,
            "trace": [
                {"step": "Adapt", "status": "fallback", "detail": "Used the fallback."}
            ],
        },
    )

    html = frontend.post(
        "/ai/suggest", data={"name": "Widget", "category": "Audio"}
    ).get_data(as_text=True)
    assert "local fallback was used" in html


def test_backend_outage_is_reported_on_the_page(frontend, monkeypatch):
    def boom(**_kwargs):
        raise api_client.ApiError("Product Catalogue API is unreachable.", 503)

    monkeypatch.setattr(api_client, "list_products", boom)
    monkeypatch.setattr(api_client, "list_categories", lambda: [])

    html = frontend.get("/").get_data(as_text=True)
    assert "unreachable" in html


# ------------------------------------------------------- SKU preview wiring
def test_category_select_drives_the_sku_preview(frontend, fake_api):
    html = frontend.get("/partials/form").get_data(as_text=True)
    assert 'hx-get="/partials/sku-preview"' in html
    assert 'hx-target="#sku"' in html
    assert 'hx-swap="outerHTML"' in html
    # Nothing to show until a category is picked.
    assert 'placeholder="Choose a category first"' in html


def test_sku_preview_partial_returns_the_field_for_a_category(frontend, fake_api):
    html = frontend.get("/partials/sku-preview?category=Wearables").get_data(
        as_text=True
    )
    assert "<html" not in html  # a fragment, not a page
    assert 'id="sku"' in html
    assert 'value="SKU-WEA-0007"' in html


def test_previewed_sku_is_not_submitted_on_create(frontend, fake_api):
    html = frontend.get("/partials/sku-preview?category=Audio").get_data(as_text=True)
    assert 'name="sku"' not in html


def test_edit_form_names_the_sku_so_it_survives_a_rerender(frontend, fake_api):
    html = frontend.get("/partials/form/1").get_data(as_text=True)
    assert 'name="sku"' in html
    assert 'value="SKU-AUD-1001"' in html
    assert "readonly" in html


def test_category_options_come_from_the_closed_set(frontend, fake_api):
    """Including a category with no products, or it could never get its first."""
    html = frontend.get("/partials/form").get_data(as_text=True)
    for category in ("Audio", "Computing", "Home", "Wearables"):
        assert ">{}</option>".format(category) in html


# --------------------------------------------------- long description folding
LONG_DESCRIPTION = (
    "Engineered for listeners who refuse to compromise, these over-ear headphones "
    "pair adaptive hybrid noise cancelling with a thirty hour battery and plush "
    "memory foam earcups that stay comfortable across long flights."
)


def test_short_description_is_not_folded(frontend, fake_api):
    html = frontend.get("/partials/products").get_data(as_text=True)
    assert "description-more" not in html
    assert "Over-ear headphones." in html


def test_long_description_collapses_behind_a_disclosure(
    frontend, fake_api, monkeypatch
):
    fake_api["products"][0]["description"] = LONG_DESCRIPTION
    monkeypatch.setattr(api_client, "list_products", lambda **kw: fake_api["products"])

    html = frontend.get("/partials/products").get_data(as_text=True)
    assert '<details class="description-more">' in html
    # The full text is present for the expanded state...
    assert LONG_DESCRIPTION in html
    # ...and the preview is truncated on a word boundary, not mid-word.
    preview = html.split('class="description-preview">')[1].split("</span>")[0]
    assert preview.endswith("…")
    assert LONG_DESCRIPTION.startswith(preview[:-1].strip())


def test_disclosure_keeps_a_control_to_collapse_again(frontend, fake_api, monkeypatch):
    """<summary> must survive in the open state or the row cannot be closed."""
    css = io.open(CSS_PATH, encoding="utf-8").read()
    assert ".description-more[open] summary::after" in css  # relabelled
    assert ".description-more[open] summary {" in css  # reordered
    assert ".description-more[open] summary { display: none" not in css


# ------------------------------------------------------- created/updated column
def test_table_has_an_updated_column(frontend, fake_api):
    html = frontend.get("/partials/products").get_data(as_text=True)
    assert "<th>Updated</th>" in html
    assert 'class="timestamps"' in html


def test_updated_shows_a_plain_date_with_the_stamp_in_the_tooltip(
    frontend, fake_api, monkeypatch
):
    fake_api["products"][0]["created_at"] = "2026-09-01 14:28:36"
    fake_api["products"][0]["updated_at"] = "2026-09-03 10:53:49"
    monkeypatch.setattr(api_client, "list_products", lambda **kw: fake_api["products"])

    html = frontend.get("/partials/products").get_data(as_text=True)
    assert ">3 Sep 2026</td>" in html  # date only
    assert 'title="updated 2026-09-03 10:53:49 UTC"' in html


def test_unedited_product_shows_the_same_plain_date(frontend, fake_api, monkeypatch):
    """Never-edited rows read exactly like edited ones -- no special casing."""
    stamp = "2026-09-01 14:28:36"
    fake_api["products"][0]["created_at"] = stamp
    fake_api["products"][0]["updated_at"] = stamp
    monkeypatch.setattr(api_client, "list_products", lambda **kw: fake_api["products"])

    html = frontend.get("/partials/products").get_data(as_text=True)
    assert ">1 Sep 2026</td>" in html
    assert "never edited" not in html
    assert "created" not in html


def test_short_date_passes_through_anything_unparseable():
    """A malformed stamp must not take the whole table down."""
    from conftest import frontend_service

    assert frontend_service.short_date("2026-09-03 10:53:49") == "3 Sep 2026"
    assert frontend_service.short_date("not a date") == "not a date"
    assert frontend_service.short_date("") == "—"
    assert frontend_service.short_date(None) == "—"


def test_description_limit_lives_in_python_not_the_template():
    from conftest import frontend_service

    template = io.open(
        os.path.join(
            os.path.dirname(CSS_PATH),
            "..",
            "..",
            "templates",
            "partials",
            "product_table.html",
        ),
        encoding="utf-8",
    ).read()
    assert "set DESCRIPTION_PREVIEW" not in template
    assert "DESCRIPTION_PREVIEW" in template  # still used
    assert frontend_service.app.jinja_env.globals["DESCRIPTION_PREVIEW"] == 110
