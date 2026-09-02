"""SQLite access layer for the Product Catalogue database microservice.

Only this microservice touches the SQLite file; the backend/API microservice
reaches the data over HTTP, keeping the three microservices independently
deployable.
"""

import os
import sqlite3
import threading

DB_PATH = os.getenv("DB_PATH", "/data/products.db")
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
SEED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed.sql")

_write_lock = threading.Lock()

COLUMNS = ("sku", "name", "description", "category", "price", "status")


class NotFound(Exception):
    """Raised when a product id does not exist."""


class Conflict(Exception):
    """Raised when a SKU would be duplicated (the SKU is unique)."""


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(force_reseed=False):
    """Create the schema and seed the table on first start.

    Idempotent: a restart of the container keeps whatever data already exists
    unless ``force_reseed`` is set (used by the reseed script and by tests).
    """
    directory = os.path.dirname(DB_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)

    with _write_lock, connect() as conn:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as handle:
            conn.executescript(handle.read())

        if force_reseed:
            conn.execute("DELETE FROM products")
            conn.execute("DELETE FROM sqlite_sequence WHERE name = 'products'")

        count = conn.execute("SELECT COUNT(*) AS n FROM products").fetchone()["n"]
        if count == 0:
            with open(SEED_PATH, "r", encoding="utf-8") as handle:
                conn.executescript(handle.read())
            count = conn.execute("SELECT COUNT(*) AS n FROM products").fetchone()["n"]

    return count


# --------------------------------------------------------------------- READ
def list_products(
    category=None, status=None, sku=None, search=None, sort="name", limit=200
):
    sql = "SELECT * FROM products WHERE 1 = 1"
    params = []

    if category:
        sql += " AND category = ?"
        params.append(category)
    if status:
        sql += " AND status = ?"
        params.append(status)
    if sku:
        sql += " AND sku = ?"
        params.append(sku)
    if search:
        sql += " AND (name LIKE ? OR description LIKE ? OR sku LIKE ?)"
        term = "%{}%".format(search)
        params.extend([term, term, term])

    sort_columns = {
        "name": "name ASC",
        "price_asc": "price ASC",
        "price_desc": "price DESC",
        "newest": "datetime(created_at) DESC, id DESC",
    }
    sql += " ORDER BY " + sort_columns.get(sort, sort_columns["name"])
    sql += " LIMIT ?"
    params.append(int(limit))

    with connect() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def get_product(product_id):
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()
    if row is None:
        raise NotFound("product {} does not exist".format(product_id))
    return dict(row)


def list_categories():
    with connect() as conn:
        rows = conn.execute(
            "SELECT category, COUNT(*) AS product_count, ROUND(AVG(price), 2) AS avg_price "
            "FROM products GROUP BY category ORDER BY category"
        ).fetchall()
    return [dict(row) for row in rows]


def category_stats(category):
    """Facts used to ground the AI price suggestion (the Plan step)."""
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS product_count, ROUND(AVG(price), 2) AS avg_price, "
            "MIN(price) AS min_price, MAX(price) AS max_price "
            "FROM products WHERE category = ?",
            (category,),
        ).fetchone()
        sample = conn.execute(
            "SELECT name, price FROM products WHERE category = ? ORDER BY price LIMIT 5",
            (category,),
        ).fetchall()

    stats = dict(row)
    stats["category"] = category
    stats["sample"] = [dict(item) for item in sample]
    return stats


# -------------------------------------------------------------------- WRITE
def create_product(data):
    values = [data.get(column) for column in COLUMNS]
    sql = "INSERT INTO products (sku, name, description, category, price, status) VALUES (?,?,?,?,?,?)"
    with _write_lock, connect() as conn:
        try:
            cursor = conn.execute(sql, values)
        except sqlite3.IntegrityError as exc:
            raise Conflict(str(exc)) from exc
        new_id = cursor.lastrowid
    return get_product(new_id)


def update_product(product_id, data):
    existing = get_product(product_id)  # raises NotFound
    merged = {column: data.get(column, existing[column]) for column in COLUMNS}

    sql = (
        "UPDATE products SET sku = ?, name = ?, description = ?, category = ?, "
        "price = ?, status = ? WHERE id = ?"
    )
    with _write_lock, connect() as conn:
        try:
            conn.execute(sql, [merged[column] for column in COLUMNS] + [product_id])
        except sqlite3.IntegrityError as exc:
            raise Conflict(str(exc)) from exc
    return get_product(product_id)


def delete_product(product_id):
    get_product(product_id)  # raises NotFound
    with _write_lock, connect() as conn:
        conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
    return True


def count_products():
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM products").fetchone()["n"]
