-- ===========================================================================
-- Student 1 - Product Catalogue - seed data.
-- requires a minimum of ten (10) records per table; 12 are seeded
-- so that the category filter and the AI price grounding have real data.
-- ===========================================================================

INSERT OR IGNORE INTO
    products (
        sku,
        name,
        description,
        category,
        price,
        status
    )
VALUES (
        'SKU-AUD-1001',
        'Aurora Wireless Headphones',
        'Over-ear Bluetooth headphones with active noise cancelling and a 30 hour battery.',
        'Audio',
        199.95,
        'active'
    ),
    (
        'SKU-AUD-1002',
        'Pebble Bluetooth Speaker',
        'Pocket-sized waterproof speaker with 12 hours of playback and a carabiner clip.',
        'Audio',
        59.00,
        'active'
    ),
    (
        'SKU-AUD-1003',
        'Studio Wired Earbuds',
        'In-ear monitors with a braided cable, inline microphone and three silicone tip sizes.',
        'Audio',
        34.50,
        'active'
    ),
    (
        'SKU-COM-2001',
        'Nimbus 14 Laptop Sleeve',
        'Felt and recycled-leather sleeve that fits 14 inch laptops, with a magnetic closure.',
        'Computing',
        45.00,
        'active'
    ),
    (
        'SKU-COM-2002',
        'Orbit Wireless Mouse',
        'Silent-click ergonomic mouse with adjustable DPI and a rechargeable battery.',
        'Computing',
        39.95,
        'active'
    ),
    (
        'SKU-COM-2003',
        'Mechanical Keyboard TKL',
        'Tenkeyless hot-swappable mechanical keyboard with brown switches and PBT keycaps.',
        'Computing',
        129.00,
        'active'
    ),
    (
        'SKU-COM-2004',
        'Dual Port USB-C Charger',
        'Compact 65W gallium nitride charger that fast-charges a laptop and a phone together.',
        'Computing',
        69.90,
        'draft'
    ),
    (
        'SKU-HOM-3001',
        'Ceramic Pour-Over Set',
        'Two-cup ceramic pour-over dripper with a matching carafe and a reusable steel filter.',
        'Home',
        74.00,
        'active'
    ),
    (
        'SKU-HOM-3002',
        'Linen Throw Blanket',
        'Stonewashed French linen throw, 130 x 170 cm, that softens with every wash.',
        'Home',
        119.00,
        'active'
    ),
    (
        'SKU-HOM-3003',
        'Aroma Diffuser Mini',
        'Ultrasonic diffuser with a 150 ml tank, warm night light and eight hour timer.',
        'Home',
        49.95,
        'archived'
    ),
    (
        'SKU-WEA-4001',
        'Trail Runner Cap',
        'Lightweight running cap in perforated recycled polyester with a reflective trim.',
        'Wearables',
        29.95,
        'active'
    ),
    (
        'SKU-WEA-4002',
        'Everyday Fitness Band',
        'Slim activity tracker with heart-rate monitoring, sleep tracking and a seven day battery.',
        'Wearables',
        89.00,
        'active'
    );