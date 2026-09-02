-- ===========================================================================
-- Student 5 - Reviews and Ratings - seed data.
-- requires a minimum of ten (10) records; 12 are seeded so that the AI
-- pros/cons summary has enough real reviews to be grounded in, including
-- both positive and negative opinions on the same product.
--
-- product_sku values match Student 1's Product Catalogue seed data so the
-- integrated demo can show a real product name next to each review.
-- ===========================================================================

INSERT OR IGNORE INTO
    reviews (
        review_id,
        product_sku,
        user_id,
        rating,
        review,
        created_at
    )
VALUES
    (
        'b6f1a2c0-0001-4a3e-9c2a-000000000001',
        'SKU-AUD-1001',
        'a7e2c9d4-0000-4f11-8b2a-100000000001',
        5,
        'The noise cancelling is fantastic on flights and the battery genuinely lasts the full 30 hours.',
        '2026-07-01 09:12:00'
    ),
    (
        'b6f1a2c0-0002-4a3e-9c2a-000000000002',
        'SKU-AUD-1001',
        'a7e2c9d4-0000-4f11-8b2a-100000000002',
        2,
        'Comfortable for the first hour but the headband started pinching after long sessions.',
        '2026-07-03 14:40:00'
    ),
    (
        'b6f1a2c0-0003-4a3e-9c2a-000000000003',
        'SKU-AUD-1001',
        'a7e2c9d4-0000-4f11-8b2a-100000000003',
        4,
        'Great sound quality for the price and pairs instantly with my laptop and phone.',
        '2026-07-05 08:05:00'
    ),
    (
        'b6f1a2c0-0004-4a3e-9c2a-000000000004',
        'SKU-AUD-1002',
        'a7e2c9d4-0000-4f11-8b2a-100000000004',
        5,
        'Surprisingly loud for such a small speaker and it survived a whole camping trip in the rain.',
        '2026-07-08 17:22:00'
    ),
    (
        'b6f1a2c0-0005-4a3e-9c2a-000000000005',
        'SKU-AUD-1002',
        'a7e2c9d4-0000-4f11-8b2a-100000000005',
        3,
        'Sound is decent but the carabiner clip snapped off after a few weeks of daily use.',
        '2026-07-10 11:15:00'
    ),
    (
        'b6f1a2c0-0006-4a3e-9c2a-000000000006',
        'SKU-COM-2001',
        'a7e2c9d4-0000-4f11-8b2a-100000000006',
        4,
        'Fits my 14 inch laptop perfectly and the magnetic closure feels sturdy.',
        '2026-07-12 19:48:00'
    ),
    (
        'b6f1a2c0-0007-4a3e-9c2a-000000000007',
        'SKU-COM-2002',
        'a7e2c9d4-0000-4f11-8b2a-100000000007',
        5,
        'Silent clicks are a game changer in the office and the DPI switch is handy for design work.',
        '2026-07-14 10:03:00'
    ),
    (
        'b6f1a2c0-0008-4a3e-9c2a-000000000008',
        'SKU-COM-2002',
        'a7e2c9d4-0000-4f11-8b2a-100000000008',
        1,
        'Mine stopped charging after two months and support never replied to my emails.',
        '2026-07-16 16:27:00'
    ),
    (
        'b6f1a2c0-0009-4a3e-9c2a-000000000009',
        'SKU-COM-2003',
        'a7e2c9d4-0000-4f11-8b2a-100000000009',
        5,
        'The brown switches feel amazing and the PBT keycaps have not shown a hint of shine yet.',
        '2026-07-18 07:51:00'
    ),
    (
        'b6f1a2c0-0010-4a3e-9c2a-000000000010',
        'SKU-HOM-3001',
        'a7e2c9d4-0000-4f11-8b2a-100000000010',
        4,
        'Makes a smooth cup every time and the ceramic keeps the coffee hot for longer than my old dripper.',
        '2026-07-20 09:00:00'
    ),
    (
        'b6f1a2c0-0011-4a3e-9c2a-000000000011',
        'SKU-HOM-3002',
        'a7e2c9d4-0000-4f11-8b2a-100000000011',
        5,
        'So soft after the first wash and big enough to share on the couch.',
        '2026-07-22 20:35:00'
    ),
    (
        'b6f1a2c0-0012-4a3e-9c2a-000000000012',
        'SKU-WEA-4002',
        'a7e2c9d4-0000-4f11-8b2a-100000000012',
        3,
        'Heart rate tracking is accurate during runs but the app crashes when syncing sleep data.',
        '2026-07-24 06:18:00'
    );
