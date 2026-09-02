-- ===========================================================================
-- Student 4 - Inventory and Stock - seed data.
-- 12 sample stock records across 4 categories for inventory testing.
-- Includes items at healthy levels and items below restock threshold.
-- ===========================================================================

INSERT OR IGNORE INTO
    stock (
        sku,
        name,
        quantity,
        category,
        location,
        restock_threshold,
        stock_level
    )
VALUES (
        'SKU-AUD-1001',
        'Aurora Wireless Headphones',
        50,
        'Audio',
        'Shelf A1',
        30,
        'good'
    ),
    (
        'SKU-AUD-1002',
        'Pebble Bluetooth Speaker',
        5,
        'Audio',
        'Shelf A2',
        30,
        'low'
    ),
    (
        'SKU-AUD-1003',
        'Studio Wired Earbuds',
        15,
        'Audio',
        'Shelf A3',
        30,
        'low'
    ),
    (
        'SKU-COM-2001',
        'Nimbus 14 Laptop Sleeve',
        8,
        'Computing',
        'Bin B1',
        20,
        'low'
    ),
    (
        'SKU-COM-2002',
        'Orbit Wireless Mouse',
        35,
        'Computing',
        'Bin B2',
        30,
        'good'
    ),
    (
        'SKU-COM-2003',
        'Mechanical Keyboard TKL',
        12,
        'Computing',
        'Bin B3',
        25,
        'low'
    ),
    (
        'SKU-COM-2004',
        'Dual Port USB-C Charger',
        42,
        'Computing',
        'Bin B4',
        30,
        'good'
    ),
    (
        'SKU-HOM-3001',
        'Ceramic Pour-Over Set',
        18,
        'Home',
        'Cabinet C1',
        25,
        'low'
    ),
    (
        'SKU-HOM-3002',
        'Linen Throw Blanket',
        28,
        'Home',
        'Cabinet C2',
        20,
        'good'
    ),
    (
        'SKU-HOM-3003',
        'Aroma Diffuser Mini',
        22,
        'Home',
        'Cabinet C3',
        20,
        'good'
    ),
    (
        'SKU-WEA-4001',
        'Trail Runner Cap',
        45,
        'Wearables',
        'Rack D1',
        30,
        'good'
    ),
    (
        'SKU-WEA-4002',
        'Everyday Fitness Band',
        9,
        'Wearables',
        'Rack D2',
        25,
        'low'
    );