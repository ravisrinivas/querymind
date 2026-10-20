-- QueryMind demo domain: e-commerce (SQLite)
PRAGMA foreign_keys = ON;

CREATE TABLE categories (
    category_id        INTEGER PRIMARY KEY,
    name               TEXT NOT NULL UNIQUE,
    parent_category_id INTEGER REFERENCES categories(category_id)
);

CREATE TABLE suppliers (
    supplier_id    INTEGER PRIMARY KEY,
    name           TEXT NOT NULL,
    country        TEXT NOT NULL,
    lead_time_days INTEGER NOT NULL
);

CREATE TABLE products (
    product_id  INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    category_id INTEGER NOT NULL REFERENCES categories(category_id),
    supplier_id INTEGER NOT NULL REFERENCES suppliers(supplier_id),
    unit_price  REAL NOT NULL,
    cost_price  REAL NOT NULL,
    created_at  DATE NOT NULL,
    is_active   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    first_name  TEXT NOT NULL,
    last_name   TEXT NOT NULL,
    email       TEXT NOT NULL UNIQUE,
    country     TEXT NOT NULL,
    city        TEXT NOT NULL,
    segment     TEXT NOT NULL CHECK (segment IN ('Consumer','Corporate','Small Business')),
    signup_date DATE NOT NULL
);

CREATE TABLE orders (
    order_id      INTEGER PRIMARY KEY,
    customer_id   INTEGER NOT NULL REFERENCES customers(customer_id),
    order_date    DATE NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('pending','shipped','completed','cancelled','returned')),
    shipping_cost REAL NOT NULL,
    tax_amount    REAL NOT NULL,
    total_amount  REAL NOT NULL          -- items + shipping + tax
);

CREATE TABLE order_items (
    order_item_id INTEGER PRIMARY KEY,
    order_id      INTEGER NOT NULL REFERENCES orders(order_id),
    product_id    INTEGER NOT NULL REFERENCES products(product_id),
    quantity      INTEGER NOT NULL,
    unit_price    REAL NOT NULL,         -- price at time of sale
    discount_pct  REAL NOT NULL,         -- 0..0.5
    line_total    REAL NOT NULL          -- quantity * unit_price * (1 - discount_pct)
);

CREATE TABLE payments (
    payment_id   INTEGER PRIMARY KEY,
    order_id     INTEGER NOT NULL REFERENCES orders(order_id),
    payment_date DATE NOT NULL,
    method       TEXT NOT NULL CHECK (method IN ('credit_card','paypal','bank_transfer','gift_card')),
    amount       REAL NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('captured','refunded','failed'))
);

CREATE TABLE shipments (
    shipment_id    INTEGER PRIMARY KEY,
    order_id       INTEGER NOT NULL REFERENCES orders(order_id),
    carrier        TEXT NOT NULL,
    shipped_date   DATE NOT NULL,
    delivered_date DATE,
    status         TEXT NOT NULL CHECK (status IN ('in_transit','delivered','returned'))
);

CREATE TABLE reviews (
    review_id   INTEGER PRIMARY KEY,
    product_id  INTEGER NOT NULL REFERENCES products(product_id),
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    rating      INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    review_date DATE NOT NULL,
    comment     TEXT
);

CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_orders_date     ON orders(order_date);
CREATE INDEX idx_items_order     ON order_items(order_id);
CREATE INDEX idx_items_product   ON order_items(product_id);
CREATE INDEX idx_payments_order  ON payments(order_id);
CREATE INDEX idx_shipments_order ON shipments(order_id);
CREATE INDEX idx_reviews_product ON reviews(product_id);
