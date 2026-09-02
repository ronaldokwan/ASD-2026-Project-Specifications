"""Shared pytest fixtures for the Student 4 microservices.

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
TEST_DB_PATH = os.path.join(tempfile.mkdtemp(prefix="asd-student1-"), "products.db")
os.environ["DB_PATH"] = TEST_DB_PATH


def _load(module_name, file_path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------- database
import db as db_module  # noqa: E402  (import after sys.path/DB_PATH setup)

db_service = _load("student1_db_service", os.path.join(DATABASE_DIR, "app.py"))


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
def fake_db(monkeypatch):
    """In-memory stand-in for the database microservice's HTTP API."""

    class FakeDatabase:
        def __init__(self):
            self.rows = {
                1: {"id": 1, "sku": "SKU-AUD-1001", "name": "Aurora Wireless Headphones",
                    "description": "Over-ear headphones.", "category": "Audio",
                    "price": 199.95, "status": "active",
                    "created_at": "2026-08-01 09:00:00", "updated_at": "2026-08-01 09:00:00"},
                2: {"id": 2, "sku": "SKU-HOM-3001", "name": "Ceramic Pour-Over Set",
                    "description": "Coffee dripper.", "category": "Home",
                    "price": 74.00, "status": "active",
                    "created_at": "2026-08-01 09:00:00", "updated_at": "2026-08-01 09:00:00"},
            }
            self.next_id = 3

        def list_products(self, **filters):
            items = list(self.rows.values())
            if filters.get("category"):
                items = [p for p in items if p["category"] == filters["category"]]
            if filters.get("sku"):
                items = [p for p in items if p["sku"] == filters["sku"]]
            if filters.get("status"):
                items = [p for p in items if p["status"] == filters["status"]]
            return items

        def get_product(self, product_id):
            if product_id not in self.rows:
                raise backend_db.NotFound("product {} does not exist".format(product_id))
            return self.rows[product_id]

        def create_product(self, payload):
            if any(p["sku"] == payload["sku"] for p in self.rows.values()):
                raise backend_db.Conflict("sku already exists")
            row = dict(payload)
            row["id"] = self.next_id
            row.setdefault("description", "")
            row.setdefault("status", "active")
            row["created_at"] = row["updated_at"] = "2026-09-01 10:00:00"
            self.rows[self.next_id] = row
            self.next_id += 1
            return row

        def update_product(self, product_id, payload):
            row = self.get_product(product_id)
            row.update(payload)
            row["updated_at"] = "2026-09-01 11:00:00"
            return row

        def delete_product(self, product_id):
            self.get_product(product_id)
            del self.rows[product_id]
            return {"deleted": product_id}

        def list_categories(self):
            return [{"category": "Audio", "product_count": 1, "avg_price": 199.95},
                    {"category": "Home", "product_count": 1, "avg_price": 74.0}]

        def category_stats(self, category):
            items = [p for p in self.rows.values() if p["category"] == category]
            if not items:
                return {"category": category, "product_count": 0, "avg_price": None,
                        "min_price": None, "max_price": None, "sample": []}
            prices = [p["price"] for p in items]
            return {
                "category": category,
                "product_count": len(items),
                "avg_price": round(sum(prices) / len(prices), 2),
                "min_price": min(prices),
                "max_price": max(prices),
                "sample": [{"name": p["name"], "price": p["price"]} for p in items],
            }

        def health(self):
            return {"service": "student-1-db", "status": "ok", "products": len(self.rows)}

    fake = FakeDatabase()
    for name in ("list_products", "get_product", "create_product", "update_product",
                 "delete_product", "list_categories", "category_stats", "health"):
        monkeypatch.setattr(backend_db, name, getattr(fake, name))
    # ai_agent imported db_client as a module, so patching the module is enough.
    return fake


# --------------------------------------------------------------- frontend
frontend_service = _load("student1_frontend", os.path.join(FRONTEND_DIR, "app.py"))
import api_client as frontend_api  # noqa: E402


@pytest.fixture()
def frontend():
    frontend_service.app.config.update(TESTING=True)
    return frontend_service.app.test_client()


@pytest.fixture()
def fake_api(monkeypatch):
    """Stub of the backend/API microservice as seen by the frontend."""
    state = {
        "products": [
            {"id": 1, "sku": "SKU-AUD-1001", "name": "Aurora Wireless Headphones",
             "description": "Over-ear headphones.", "category": "Audio", "price": 199.95,
             "status": "active", "created_at": "2026-08-01", "updated_at": "2026-08-01"},
        ],
        "created": [],
        "deleted": [],
    }

    monkeypatch.setattr(frontend_api, "list_products", lambda **kw: state["products"])
    monkeypatch.setattr(frontend_api, "list_categories",
                        lambda: [{"category": "Audio"}, {"category": "Home"}])
    monkeypatch.setattr(frontend_api, "get_product", lambda pid: state["products"][0])

    def create(payload):
        state["created"].append(payload)
        row = dict(payload, id=99, created_at="2026-09-01", updated_at="2026-09-01")
        return row

    def delete(pid):
        state["deleted"].append(pid)
        return {"deleted": pid}

    monkeypatch.setattr(frontend_api, "create_product", create)
    monkeypatch.setattr(frontend_api, "update_product",
                        lambda pid, payload: dict(payload, id=pid))
    monkeypatch.setattr(frontend_api, "delete_product", delete)
    return state
