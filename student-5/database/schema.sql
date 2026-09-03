-- ===========================================================================
-- Student 5 - Alexander McGuinn - Reviews and Ratings
-- Database microservice schema (SQLite)
--
-- reviews: review_id (UUID PK), product_sku, user_id (UUID), rating (1-5),
--          review, created_at
--
-- product_sku links a review to a product in Student 1's catalogue (products
-- are owned by that microservice, so only the SKU is stored here - the same
-- cross-service pattern Student 2 uses for order lines).
-- ===========================================================================

CREATE TABLE IF NOT EXISTS reviews (
    review_id TEXT PRIMARY KEY,
    product_sku TEXT NOT NULL,
    user_id TEXT NOT NULL,
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    review TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_reviews_product_sku ON reviews (product_sku);

CREATE INDEX IF NOT EXISTS idx_reviews_user_id ON reviews (user_id);

CREATE INDEX IF NOT EXISTS idx_reviews_rating ON reviews (rating);
