-- PostgreSQL setup script for logical replication with e-commerce schema
-- Run this before using pgoutput-decoder

-- 1. Configure PostgreSQL (add to postgresql.conf and restart)
-- wal_level = logical
-- max_replication_slots = 4
-- max_wal_senders = 4

-- 2. Create a database (if needed)
CREATE DATABASE ecommerce_db;

\c ecommerce_db

-- 3. Create customers table
CREATE TABLE customers (
    _id VARCHAR PRIMARY KEY,
    name VARCHAR NOT NULL,
    credit_limit INTEGER NOT NULL,
    _deleted BOOLEAN DEFAULT FALSE
);

-- 4. Create orders table
CREATE TABLE orders (
    _id VARCHAR PRIMARY KEY,
    cust_id VARCHAR NOT NULL,
    order_date DATE NOT NULL,
    _deleted BOOLEAN DEFAULT FALSE,
    FOREIGN KEY (cust_id) REFERENCES customers(_id)
);

-- 5. Create products table
CREATE TABLE products (
    _id VARCHAR PRIMARY KEY,
    name VARCHAR NOT NULL,
    description VARCHAR,
    price DECIMAL(10,2) NOT NULL,
    _deleted BOOLEAN DEFAULT FALSE
);

-- 6. Create order_lines table
CREATE TABLE order_lines (
    _id VARCHAR PRIMARY KEY,
    order_id VARCHAR NOT NULL,
    product_id VARCHAR NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price DECIMAL(10,2) NOT NULL,
    _deleted BOOLEAN DEFAULT FALSE,
    FOREIGN KEY (order_id) REFERENCES orders(_id),
    FOREIGN KEY (product_id) REFERENCES products(_id)
);

-- 7. Set replica identity to FULL to include old values in UPDATEs
ALTER TABLE customers REPLICA IDENTITY FULL;
ALTER TABLE orders REPLICA IDENTITY FULL;
ALTER TABLE products REPLICA IDENTITY FULL;
ALTER TABLE order_lines REPLICA IDENTITY FULL;

-- 8. Create publication for all tables
DROP PUBLICATION IF EXISTS ecommerce_pub;
CREATE PUBLICATION ecommerce_pub FOR ALL TABLES;

-- Or create publication for specific tables:
-- CREATE PUBLICATION ecommerce_pub FOR TABLE customers, orders, products, order_lines;

-- 9. Create replication slot
-- Note: Drop existing slot first if it exists
SELECT pg_drop_replication_slot('ecommerce_slot') 
WHERE EXISTS (
    SELECT 1 FROM pg_replication_slots WHERE slot_name = 'ecommerce_slot'
);

SELECT pg_create_logical_replication_slot('ecommerce_slot', 'pgoutput');

-- 10. Grant permissions
-- Replace 'postgres' with your username
ALTER USER geir.gronmo WITH REPLICATION;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO geir.gronmo;

-- 11. Insert sample data
-- Customer
INSERT INTO customers (_id, name, credit_limit, _deleted) 
VALUES ('CUST001', 'Alice Johnson', 5000, FALSE);

INSERT INTO customers (_id, name, credit_limit, _deleted) 
VALUES ('CUST002', 'Bob Smith', 10000, FALSE);

-- Products
INSERT INTO products (_id, name, description, price, _deleted) 
VALUES ('PROD001', 'Laptop', 'High-performance laptop', 1299.99, FALSE);

INSERT INTO products (_id, name, description, price, _deleted) 
VALUES ('PROD002', 'Mouse', 'Wireless mouse', 29.99, FALSE);

INSERT INTO products (_id, name, description, price, _deleted) 
VALUES ('PROD003', 'Keyboard', 'Mechanical keyboard', 149.99, FALSE);

-- Order
INSERT INTO orders (_id, cust_id, order_date, _deleted) 
VALUES ('ORD001', 'CUST001', '2026-02-12', FALSE);

-- Order lines
INSERT INTO order_lines (_id, order_id, product_id, quantity, unit_price, _deleted) 
VALUES ('LINE001', 'ORD001', 'PROD001', 1, 1299.99, FALSE);

INSERT INTO order_lines (_id, order_id, product_id, quantity, unit_price, _deleted) 
VALUES ('LINE002', 'ORD001', 'PROD002', 2, 29.99, FALSE);

-- 12. Verify publication
SELECT * FROM pg_publication;

-- 13. Verify replication slot
SELECT slot_name, plugin, slot_type, database, active
FROM pg_replication_slots
WHERE slot_name = 'ecommerce_slot';

-- 14. Test operations (run after starting CDC reader)
-- INSERT
INSERT INTO customers (_id, name, credit_limit) VALUES ('CUST003', 'Charlie Brown', 7500);

-- UPDATE (normal)
UPDATE products SET price = 1199.99 WHERE _id = 'PROD001';

-- UPDATE (soft delete)
UPDATE customers SET _deleted = TRUE WHERE _id = 'CUST003';

-- DELETE (hard delete)
DELETE FROM order_lines WHERE _id = 'LINE002';

-- 15. Monitor replication lag
SELECT 
    slot_name,
    pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS lag
FROM pg_replication_slots
WHERE slot_name = 'ecommerce_slot';

-- 16. Query sample data
SELECT c._id, c.name, o._id as order_id, o.order_date
FROM customers c
LEFT JOIN orders o ON c._id = o.cust_id
WHERE c._deleted = FALSE;

-- 17. Cleanup (when done testing)
-- SELECT pg_drop_replication_slot('ecommerce_slot');
-- DROP PUBLICATION ecommerce_pub;
-- DROP TABLE order_lines;
-- DROP TABLE orders;
-- DROP TABLE products;
-- DROP TABLE customers;
