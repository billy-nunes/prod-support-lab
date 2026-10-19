-- Foreign keys are added after the bulk load (faster than checking 3M rows one by one).
ALTER TABLE orders      ADD CONSTRAINT orders_customer_fk    FOREIGN KEY (customer_id) REFERENCES customers(id);
ALTER TABLE order_items ADD CONSTRAINT order_items_order_fk  FOREIGN KEY (order_id)    REFERENCES orders(id);
ALTER TABLE order_items ADD CONSTRAINT order_items_product_fk FOREIGN KEY (product_id) REFERENCES products(id);

-- Least privilege: the app and the worker only get what they need.
GRANT SELECT ON customers, products, orders, order_items TO shop_app;
GRANT SELECT, UPDATE ON inventory TO shop_app;
GRANT INSERT ON orders, order_items, audit_log TO shop_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO shop_app;

GRANT SELECT ON orders TO shop_worker;
GRANT SELECT, INSERT ON settlements TO shop_worker;
GRANT SELECT, INSERT, UPDATE ON job_runs TO shop_worker;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO shop_worker;

-- The settlement job starts after the seeded history, so it only settles new orders.
INSERT INTO job_runs (job, status, finished_at, rows_processed, high_water_mark)
SELECT 'settlement', 'success', now(), 0, max(id) FROM orders;

ANALYZE;
