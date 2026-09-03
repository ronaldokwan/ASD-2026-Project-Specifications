"""SQLite access layer for the Student 3 customer database service."""

import os
import sqlite3
import threading

DB_PATH = os.getenv("DB_PATH", "/data/customers.db")
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
SEED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed.sql")

_write_lock = threading.Lock()
COLUMNS = ("name", "email", "phone", "address", "loyalty_tier", "joined_at")


class NotFound(Exception):
    """Raised when a customer id does not exist."""


class Conflict(Exception):
    """Raised when an email address would be duplicated."""


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(force_reseed=False):
    directory = os.path.dirname(DB_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)

    with _write_lock, connect() as conn:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as handle:
            conn.executescript(handle.read())
        if force_reseed:
            conn.execute("DELETE FROM customers")
            conn.execute("DELETE FROM sqlite_sequence WHERE name = 'customers'")
        count = conn.execute("SELECT COUNT(*) AS n FROM customers").fetchone()["n"]
        if count == 0:
            with open(SEED_PATH, "r", encoding="utf-8") as handle:
                conn.executescript(handle.read())
            count = conn.execute("SELECT COUNT(*) AS n FROM customers").fetchone()["n"]
    return count


def list_customers(search=None, limit=200):
    sql = "SELECT * FROM customers"
    params = []
    if search:
        sql += " WHERE name LIKE ? COLLATE NOCASE OR email LIKE ? COLLATE NOCASE"
        term = "%{}%".format(search)
        params.extend([term, term])
    sql += " ORDER BY name COLLATE NOCASE ASC LIMIT ?"
    params.append(int(limit))
    with connect() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def get_customer(customer_id):
    with connect() as conn:
        row = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if row is None:
        raise NotFound("customer {} does not exist".format(customer_id))
    return dict(row)


def create_customer(data):
    values = [data.get(column) for column in COLUMNS]
    sql = (
        "INSERT INTO customers (name,email,phone,address,loyalty_tier,joined_at) "
        "VALUES (?,?,?,?,?,?)"
    )
    with _write_lock, connect() as conn:
        try:
            cursor = conn.execute(sql, values)
        except sqlite3.IntegrityError as exc:
            raise Conflict(str(exc)) from exc
        customer_id = cursor.lastrowid
    return get_customer(customer_id)


def update_customer(customer_id, data):
    existing = get_customer(customer_id)
    merged = {column: data.get(column, existing[column]) for column in COLUMNS}
    sql = (
        "UPDATE customers SET name=?, email=?, phone=?, address=?, "
        "loyalty_tier=?, joined_at=? WHERE id=?"
    )
    with _write_lock, connect() as conn:
        try:
            conn.execute(sql, [merged[column] for column in COLUMNS] + [customer_id])
        except sqlite3.IntegrityError as exc:
            raise Conflict(str(exc)) from exc
    return get_customer(customer_id)


def delete_customer(customer_id):
    get_customer(customer_id)
    with _write_lock, connect() as conn:
        conn.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
    return True


def count_customers():
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM customers").fetchone()["n"]
