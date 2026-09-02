"""SQLite access layer for the Reviews and Ratings database microservice.

Only this microservice touches the SQLite file; the backend/API microservice
reaches the data over HTTP, keeping the three microservices independently
deployable.
"""

import os
import sqlite3
import threading
import uuid

DB_PATH = os.getenv("DB_PATH", "/data/reviews.db")
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
SEED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed.sql")

_write_lock = threading.Lock()

COLUMNS = ("product_sku", "user_id", "rating", "review")


class NotFound(Exception):
    """Raised when a review_id does not exist."""


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
            conn.execute("DELETE FROM reviews")

        count = conn.execute("SELECT COUNT(*) AS n FROM reviews").fetchone()["n"]
        if count == 0:
            with open(SEED_PATH, "r", encoding="utf-8") as handle:
                conn.executescript(handle.read())
            count = conn.execute("SELECT COUNT(*) AS n FROM reviews").fetchone()["n"]

    return count


# --------------------------------------------------------------------- READ
def list_reviews(product_sku=None, user_id=None, rating=None, sort="newest", limit=200):
    sql = "SELECT * FROM reviews WHERE 1 = 1"
    params = []

    if product_sku:
        sql += " AND product_sku = ?"
        params.append(product_sku)
    if user_id:
        sql += " AND user_id = ?"
        params.append(user_id)
    if rating:
        sql += " AND rating = ?"
        params.append(int(rating))

    sort_columns = {
        "newest": "datetime(created_at) DESC",
        "oldest": "datetime(created_at) ASC",
        "rating_desc": "rating DESC, datetime(created_at) DESC",
        "rating_asc": "rating ASC, datetime(created_at) DESC",
    }
    sql += " ORDER BY " + sort_columns.get(sort, sort_columns["newest"])
    sql += " LIMIT ?"
    params.append(int(limit))

    with connect() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def get_review(review_id):
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM reviews WHERE review_id = ?", (review_id,)
        ).fetchone()
    if row is None:
        raise NotFound("review {} does not exist".format(review_id))
    return dict(row)


def product_stats(product_sku):
    """Facts used to ground the AI pros/cons summary (the Plan step)."""
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS review_count, ROUND(AVG(rating), 2) AS avg_rating "
            "FROM reviews WHERE product_sku = ?",
            (product_sku,),
        ).fetchone()
        distribution_rows = conn.execute(
            "SELECT rating, COUNT(*) AS n FROM reviews WHERE product_sku = ? GROUP BY rating",
            (product_sku,),
        ).fetchall()
        sample = conn.execute(
            "SELECT rating, review FROM reviews WHERE product_sku = ? "
            "ORDER BY rating DESC, datetime(created_at) DESC LIMIT 3",
            (product_sku,),
        ).fetchall()
        low_sample = conn.execute(
            "SELECT rating, review FROM reviews WHERE product_sku = ? "
            "ORDER BY rating ASC, datetime(created_at) DESC LIMIT 3",
            (product_sku,),
        ).fetchall()

    stats = dict(row)
    stats["product_sku"] = product_sku
    stats["rating_distribution"] = {str(r): 0 for r in range(1, 6)}
    for item in distribution_rows:
        stats["rating_distribution"][str(item["rating"])] = item["n"]

    seen = set()
    combined = []
    for item in list(sample) + list(low_sample):
        key = (item["rating"], item["review"])
        if key in seen:
            continue
        seen.add(key)
        combined.append(dict(item))
    stats["sample"] = combined
    return stats


# -------------------------------------------------------------------- WRITE
def create_review(data):
    review_id = str(uuid.uuid4())
    values = [review_id] + [data.get(column) for column in COLUMNS]
    sql = (
        "INSERT INTO reviews (review_id, product_sku, user_id, rating, review) "
        "VALUES (?,?,?,?,?)"
    )
    with _write_lock, connect() as conn:
        conn.execute(sql, values)
    return get_review(review_id)


def update_review(review_id, data):
    existing = get_review(review_id)  # raises NotFound
    merged = {column: data.get(column, existing[column]) for column in COLUMNS}

    sql = (
        "UPDATE reviews SET product_sku = ?, user_id = ?, rating = ?, review = ? "
        "WHERE review_id = ?"
    )
    with _write_lock, connect() as conn:
        conn.execute(sql, [merged[column] for column in COLUMNS] + [review_id])
    return get_review(review_id)


def delete_review(review_id):
    get_review(review_id)  # raises NotFound
    with _write_lock, connect() as conn:
        conn.execute("DELETE FROM reviews WHERE review_id = ?", (review_id,))
    return True


def count_reviews():
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM reviews").fetchone()["n"]
