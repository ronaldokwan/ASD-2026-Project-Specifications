-- ===========================================================================
-- Student 1 - Ronaldo Kwan - Product Catalogue
-- Database microservice schema (SQLite)
--
-- products: id, sku, name, description, category, price, status,
--           created_at, updated_at
-- ===========================================================================

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL,
    price REAL NOT NULL CHECK (price >= 0),
    status TEXT NOT NULL DEFAULT 'active' CHECK (
        status IN ('active', 'draft', 'archived')
    ),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_products_category ON products (category);

CREATE INDEX IF NOT EXISTS idx_products_status ON products (status);

CREATE UNIQUE INDEX IF NOT EXISTS idx_products_sku ON products (sku);

-- Keep updated_at accurate without every caller having to remember it.
CREATE TRIGGER IF NOT EXISTS trg_products_updated_at
AFTER UPDATE ON products
FOR EACH ROW
BEGIN
    UPDATE products SET updated_at = datetime('now') WHERE id = OLD.id;
END;