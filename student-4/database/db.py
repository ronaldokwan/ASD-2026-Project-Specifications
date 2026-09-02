"""SQLite access layer for the Inventory and Stock database microservice.

Only this microservice touches the SQLite file; the backend/API microservice
reaches the data over HTTP, keeping the three microservices independently
deployable.
"""

import os
import sqlite3
import threading

DB_PATH = os.getenv("DB_PATH", "/data/stock.db")
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
SEED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed.sql")

_write_lock = threading.Lock()

COLUMNS = ("sku", "name", "quantity", "category", "location", "restock_threshold", "stock_level")


class NotFound(Exception):
    """Raised when a stock record id does not exist."""


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
            conn.execute("DELETE FROM stock")
            conn.execute("DELETE FROM sqlite_sequence WHERE name = 'stock'")

        count = conn.execute("SELECT COUNT(*) AS n FROM stock").fetchone()["n"]
        if count == 0:
            with open(SEED_PATH, "r", encoding="utf-8") as handle:
                conn.executescript(handle.read())
            count = conn.execute("SELECT COUNT(*) AS n FROM stock").fetchone()["n"]

    return count


# --------------------------------------------------------------------- READ
def list_stock(
    category=None, stock_level=None, sku=None, search=None, sort="name", limit=200
):
    sql = "SELECT * FROM stock WHERE 1 = 1"
    params = []

    if category:
        sql += " AND category = ?"
        params.append(category)
    if stock_level:
        sql += " AND stock_level = ?"
        params.append(stock_level)
    if sku:
        sql += " AND sku = ?"
        params.append(sku)
    if search:
        sql += " AND (name LIKE ? OR sku LIKE ?)"
        term = "%{}%".format(search)
        params.extend([term, term])

    sort_columns = {
        "name": "name ASC",
        "qty_asc": "quantity ASC",
        "qty_desc": "quantity DESC",
        "last_restocked": "datetime(last_restocked) DESC, id DESC",
    }
    sql += " ORDER BY " + sort_columns.get(sort, sort_columns["name"])
    sql += " LIMIT ?"
    params.append(int(limit))

    with connect() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def list_low_stock(limit=200):
    """Return items where quantity <= restock_threshold."""
    sql = "SELECT * FROM stock WHERE quantity <= restock_threshold ORDER BY name ASC LIMIT ?"
    with connect() as conn:
        return [dict(row) for row in conn.execute(sql, (int(limit),)).fetchall()]


def get_stock(stock_id):
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM stock WHERE id = ?", (stock_id,)
        ).fetchone()
    if row is None:
        raise NotFound("stock item {} does not exist".format(stock_id))
    return dict(row)


# -------------------------------------------------------------------- WRITE
def create_stock(data):
    values = [data.get(column) for column in COLUMNS]
    sql = "INSERT INTO stock (sku, name, quantity, category, location, restock_threshold, stock_level) VALUES (?,?,?,?,?,?,?)"
    with _write_lock, connect() as conn:
        try:
            cursor = conn.execute(sql, values)
        except sqlite3.IntegrityError as exc:
            raise Conflict(str(exc)) from exc
        new_id = cursor.lastrowid
    return get_stock(new_id)


def update_stock(stock_id, data):
    existing = get_stock(stock_id)  # raises NotFound
    merged = {column: data.get(column, existing[column]) for column in COLUMNS}

    sql = (
        "UPDATE stock SET sku = ?, name = ?, quantity = ?, category = ?, "
        "location = ?, restock_threshold = ?, stock_level = ? WHERE id = ?"
    )
    with _write_lock, connect() as conn:
        try:
            conn.execute(sql, [merged[column] for column in COLUMNS] + [stock_id])
        except sqlite3.IntegrityError as exc:
            raise Conflict(str(exc)) from exc
    return get_stock(stock_id)


def delete_stock(stock_id):
    get_stock(stock_id)  # raises NotFound
    with _write_lock, connect() as conn:
        conn.execute("DELETE FROM stock WHERE id = ?", (stock_id,))
    return True


def count_stock():
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM stock").fetchone()["n"]
