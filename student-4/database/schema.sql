-- ===========================================================================
-- Student 4 - Jonathan Czesler - Inventory and Stock
-- Database microservice schema (SQLite)
--
-- stock: id, sku, name, quantity, category, location, restock_threshold, 
--        stock_level (computed: good if qty >= threshold, low otherwise),
--        last_restocked, created_at, updated_at
-- ===========================================================================

CREATE TABLE IF NOT EXISTS stock (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity >= 0),
    category TEXT NOT NULL,
    location TEXT NOT NULL,
    restock_threshold INTEGER NOT NULL CHECK (restock_threshold >= 0),
    stock_level TEXT NOT NULL DEFAULT 'good' CHECK (
        stock_level IN ('good', 'low')
    ),
    last_restocked TEXT NOT NULL DEFAULT (datetime('now')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_stock_category ON stock (category);

CREATE INDEX IF NOT EXISTS idx_stock_stock_level ON stock (stock_level);

CREATE UNIQUE INDEX IF NOT EXISTS idx_stock_sku ON stock (sku);

-- Update last_restocked timestamp only when quantity is changed (shipment received).
-- Also update updated_at for any change.
CREATE TRIGGER IF NOT EXISTS trg_stock_update_timestamp
AFTER UPDATE ON stock
FOR EACH ROW
BEGIN
    UPDATE stock SET updated_at = datetime('now') WHERE id = NEW.id;
    -- Update last_restocked only if quantity changed
    UPDATE stock SET last_restocked = datetime('now') 
    WHERE id = NEW.id AND NEW.quantity <> OLD.quantity;
END;