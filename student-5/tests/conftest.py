"""Shared pytest fixtures for the Student 5 microservices.

All three services are exercised in-process with Flask test clients, and every
network hop between them is stubbed, so the suite runs in GitHub Actions with
no Docker, no SQLite volume and no Ollama.

The three services each have a module called ``app``, so the database and
frontend services are loaded under unique names with importlib to keep them
from colliding in ``sys.modules``.
"""

import importlib.util
import os
import sys
import tempfile

import pytest

STUDENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(STUDENT_DIR, "backend")
DATABASE_DIR = os.path.join(STUDENT_DIR, "database")
FRONTEND_DIR = os.path.join(STUDENT_DIR, "frontend")

# Inserted back to front so BACKEND_DIR ends up first on sys.path: the backend's
# ``app`` package is imported by name, while the other two services are loaded
# from an explicit file path below.
for path in (FRONTEND_DIR, DATABASE_DIR, BACKEND_DIR):
    if path in sys.path:
        sys.path.remove(path)
    sys.path.insert(0, path)

# The database module reads DB_PATH at import time - point it at a temp file.
TEST_DB_PATH = os.path.join(tempfile.mkdtemp(prefix="asd-student5-"), "reviews.db")
os.environ["DB_PATH"] = TEST_DB_PATH


def _load(module_name, file_path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------- database
import db as db_module  # noqa: E402  (import after sys.path/DB_PATH setup)

db_service = _load("student5_db_service", os.path.join(DATABASE_DIR, "app.py"))


@pytest.fixture()
def database():
    """A freshly seeded database module (12 seed records)."""
    db_module.init_db(force_reseed=True)
    return db_module


@pytest.fixture()
def db_client_http(database):
    db_service.app.config.update(TESTING=True)
    return db_service.app.test_client()


# ---------------------------------------------------------------- backend
from app import create_app  # noqa: E402
from app import catalogue_client as backend_catalogue  # noqa: E402
from app import db_client as backend_db  # noqa: E402


@pytest.fixture()
def backend_app():
    application = create_app()
    application.config.update(TESTING=True)
    return application


@pytest.fixture()
def backend(backend_app):
    return backend_app.test_client()


@pytest.fixture()
def fake_catalogue(monkeypatch):
    """In-memory stand-in for Student 1's Product Catalogue API."""
    products = [
        {"sku": "SKU-AUD-1001", "name": "Aurora Wireless Headphones", "category": "Audio"},
        {"sku": "SKU-HOM-3001", "name": "Ceramic Pour-Over Set", "category": "Home"},
    ]
    monkeypatch.setattr(backend_catalogue, "list_products", lambda: products)
    monkeypatch.setattr(
        backend_catalogue,
        "product_name",
        lambda sku: next((p["name"] for p in products if p["sku"] == sku), sku),
    )
    return products


@pytest.fixture()
def fake_db(monkeypatch):
    """In-memory stand-in for the database microservice's HTTP API."""

    class FakeDatabase:
        def __init__(self):
            self.rows = {
                "r1": {"review_id": "r1", "product_sku": "SKU-AUD-1001", "user_id": "user-one",
                       "rating": 5, "review": "Fantastic noise cancelling.",
                       "created_at": "2026-08-01 09:00:00"},
                "r2": {"review_id": "r2", "product_sku": "SKU-AUD-1001", "user_id": "user-two",
                       "rating": 2, "review": "Headband pinches after an hour.",
                       "created_at": "2026-08-02 09:00:00"},
                "r3": {"review_id": "r3", "product_sku": "SKU-HOM-3001", "user_id": "user-three",
                       "rating": 4, "review": "Makes a great cup of coffee.",
                       "created_at": "2026-08-03 09:00:00"},
            }

        def list_reviews(self, **filters):
            items = list(self.rows.values())
            if filters.get("product_sku"):
                items = [r for r in items if r["product_sku"] == filters["product_sku"]]
            if filters.get("user_id"):
                items = [r for r in items if r["user_id"] == filters["user_id"]]
            if filters.get("rating"):
                items = [r for r in items if r["rating"] == int(filters["rating"])]
            return items

        def get_review(self, review_id):
            if review_id not in self.rows:
                raise backend_db.NotFound("review {} does not exist".format(review_id))
            return self.rows[review_id]

        def create_review(self, payload):
            new_id = "r{}".format(len(self.rows) + 1)
            row = dict(payload)
            row["review_id"] = new_id
            row["created_at"] = "2026-09-01 10:00:00"
            self.rows[new_id] = row
            return row

        def update_review(self, review_id, payload):
            row = self.get_review(review_id)
            row.update(payload)
            return row

        def delete_review(self, review_id):
            self.get_review(review_id)
            del self.rows[review_id]
            return {"deleted": review_id}

        def product_stats(self, product_sku):
            items = [r for r in self.rows.values() if r["product_sku"] == product_sku]
            if not items:
                return {
                    "product_sku": product_sku, "review_count": 0, "avg_rating": None,
                    "rating_distribution": {str(n): 0 for n in range(1, 6)}, "sample": [],
                }
            ratings = [r["rating"] for r in items]
            distribution = {str(n): 0 for n in range(1, 6)}
            for r in ratings:
                distribution[str(r)] += 1
            return {
                "product_sku": product_sku,
                "review_count": len(items),
                "avg_rating": round(sum(ratings) / len(ratings), 2),
                "rating_distribution": distribution,
                "sample": [{"rating": r["rating"], "review": r["review"]} for r in items],
            }

        def health(self):
            return {"service": "student-5-db", "status": "ok", "reviews": len(self.rows)}

    fake = FakeDatabase()
    for name in ("list_reviews", "get_review", "create_review", "update_review",
                 "delete_review", "product_stats", "health"):
        monkeypatch.setattr(backend_db, name, getattr(fake, name))
    return fake


# --------------------------------------------------------------- frontend
frontend_service = _load("student5_frontend", os.path.join(FRONTEND_DIR, "app.py"))
import api_client as frontend_api  # noqa: E402


@pytest.fixture()
def frontend():
    frontend_service.app.config.update(TESTING=True)
    return frontend_service.app.test_client()


@pytest.fixture()
def fake_api(monkeypatch):
    """Stub of the backend/API microservice as seen by the frontend."""
    state = {
        "reviews": [
            {"review_id": "r1", "product_sku": "SKU-AUD-1001", "user_id": "user-one",
             "rating": 5, "review": "Fantastic noise cancelling.",
             "created_at": "2026-08-01 09:00:00"},
        ],
        "products": [{"sku": "SKU-AUD-1001", "name": "Aurora Wireless Headphones", "category": "Audio"}],
        "created": [],
        "deleted": [],
    }

    monkeypatch.setattr(frontend_api, "list_reviews", lambda **kw: state["reviews"])
    monkeypatch.setattr(frontend_api, "list_products", lambda: state["products"])
    monkeypatch.setattr(frontend_api, "get_review", lambda rid: state["reviews"][0])

    def create(payload):
        state["created"].append(payload)
        row = dict(payload, review_id="new-review", created_at="2026-09-01 10:00:00")
        return row

    def delete(rid):
        state["deleted"].append(rid)
        return {"deleted": rid}

    monkeypatch.setattr(frontend_api, "create_review", create)
    monkeypatch.setattr(frontend_api, "update_review", lambda rid, payload: dict(payload, review_id=rid))
    monkeypatch.setattr(frontend_api, "delete_review", delete)
    return state
