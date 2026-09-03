CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL COLLATE NOCASE UNIQUE,
    phone TEXT,
    address TEXT,
    loyalty_tier TEXT NOT NULL DEFAULT 'Bronze' CHECK (
        loyalty_tier IN ('Bronze', 'Silver', 'Gold')
    ),
    joined_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_customers_email
    ON customers (email COLLATE NOCASE);

CREATE INDEX IF NOT EXISTS idx_customers_name
    ON customers (name COLLATE NOCASE);
