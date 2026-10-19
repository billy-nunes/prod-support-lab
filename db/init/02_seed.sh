#!/usr/bin/env bash
# Seeds realistic-ish volume. SEED_SCALE=1 gives:
#   100k customers, 2k products, 1M orders, ~2M order_items  (about 2-4 minutes on a laptop)
# SEED_SCALE=0.05 is handy for small machines (t3.micro) and CI.
set -euo pipefail

scale="${SEED_SCALE:-1}"
n_customers=$(awk -v s="$scale" 'BEGIN { v = int(100000 * s); print (v < 1000 ? 1000 : v) }')
n_products=$(awk -v s="$scale"  'BEGIN { v = int(2000 * s);   print (v < 200  ? 200  : v) }')
n_orders=$(awk -v s="$scale"    'BEGIN { v = int(1000000 * s); print (v < 5000 ? 5000 : v) }')

echo "seed: scale=${scale} customers=${n_customers} products=${n_products} orders=${n_orders}"

psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -v n_customers="$n_customers" -v n_products="$n_products" -v n_orders="$n_orders" <<'SQL'
\timing on
SELECT setseed(0.42);

-- Customers: 30% bronze, 50% silver, 20% gold
INSERT INTO customers (id, email, full_name, loyalty_tier, created_at)
SELECT i,
       'customer' || i || '@example.com',
       (ARRAY['Amara','Ben','Chloe','Dev','Ella','Femi','Grace','Hassan','Isla','Jack',
              'Kiran','Leah','Mo','Nia','Oscar','Priya','Reece','Sofia','Tom','Zara'])[1 + (i % 20)]
         || ' ' ||
       (ARRAY['Ahmed','Brown','Clarke','Davies','Evans','Green','Hughes','Johnson','Khan','Lewis',
              'Mensah','Nowak','Okafor','Patel','Roberts','Singh','Taylor','Walker','Wilson','Young'])[1 + ((i * 7) % 20)],
       CASE WHEN i % 10 < 3 THEN 'bronze' WHEN i % 10 < 8 THEN 'silver' ELSE 'gold' END,
       now() - (random() * interval '730 days')
FROM generate_series(1, :n_customers) AS i;

INSERT INTO products (id, sku, name, category, price_pence)
SELECT i,
       'SKU-' || lpad(i::text, 6, '0'),
       (ARRAY['Classic','Suede','Leather','Chunky','Pointed','Studded','Velvet','Patent','Woven','Quilted'])[1 + (i % 10)]
         || ' ' ||
       (ARRAY['Loafer','Boot','Trainer','Sandal','Mule','Heel','Tote','Clutch','Belt','Crossbody'])[1 + ((i / 10) % 10)],
       (ARRAY['shoes','bags','accessories'])[1 + (i % 3)],
       500 + (random() * 24500)::int
FROM generate_series(1, :n_products) AS i;

-- Products 1-50 are the best sellers and always in stock. About 3% of the rest are sold out.
INSERT INTO inventory (product_id, qty)
SELECT id, CASE WHEN id > 50 AND random() < 0.03 THEN 0 ELSE 100000 END
FROM products;

-- Orders: totals are computed from the same deterministic item formula used for order_items,
-- so totals and line items always agree (useful for reconciliation exercises later).
INSERT INTO orders (id, customer_id, status, currency, total_pence, shipping_address, created_at)
SELECT o,
       1 + (random() * (:n_customers - 1))::bigint,
       (ARRAY['delivered','delivered','delivered','delivered','shipped','shipped','paid','cancelled','refunded','delivered'])[1 + (o % 10)],
       CASE WHEN o % 25 = 0 THEN 'EUR' ELSE 'GBP' END,
       (SELECT sum(p.price_pence * (1 + ((o + j) % 2)))
          FROM generate_series(1, 1 + (o % 3)) AS j
          JOIN products p ON p.id = ((o * 7919 + j * 104729) % :n_products) + 1),
       (o % 200 + 1) || ' ' ||
       (ARRAY['High Street','Station Road','Church Lane','Mill Road','Park Avenue','Victoria Road'])[1 + (o % 6)]
         || ', ' ||
       (ARRAY['London','Birmingham','Manchester','Leeds','Bristol','Glasgow','Cardiff','Solihull'])[1 + (o % 8)],
       now() - interval '1 hour' - (random() * interval '365 days')
FROM generate_series(1::bigint, :n_orders) AS o;

INSERT INTO order_items (order_id, product_id, qty, unit_price_pence)
SELECT o, p.id, 1 + ((o + j) % 2), p.price_pence
FROM generate_series(1::bigint, :n_orders) AS o
CROSS JOIN LATERAL generate_series(1, 1 + (o % 3)) AS j
JOIN products p ON p.id = ((o * 7919 + j * 104729) % :n_products) + 1;

-- Move identity sequences past the seeded ids
SELECT setval(pg_get_serial_sequence('customers','id'), (SELECT max(id) FROM customers));
SELECT setval(pg_get_serial_sequence('products','id'),  (SELECT max(id) FROM products));
SELECT setval(pg_get_serial_sequence('orders','id'),    (SELECT max(id) FROM orders));
SQL
