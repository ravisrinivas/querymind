"""Seed the QueryMind demo e-commerce database with deterministic synthetic data.

Usage:  python data/seed_db.py [--out data/ecommerce.db] [--seed 42]

Row counts (defaults): categories 12, suppliers 40, products 1,000, customers 1,200,
orders 5,000, order_items ~12,500, payments ~4,700, shipments ~4,200, reviews 3,000.
Data spans 2023-01-01 .. 2025-12-31 (the demo's fixed "today" is 2025-12-31).
"""
from __future__ import annotations

import argparse
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).parent
AS_OF = date(2025, 12, 31)
START = date(2023, 1, 1)

CATEGORIES = ["Electronics", "Home & Kitchen", "Books", "Clothing", "Sports & Outdoors", "Beauty",
              "Toys & Games", "Grocery", "Office Supplies", "Garden", "Automotive", "Pet Supplies"]
COUNTRIES = {  # country -> (weight, cities)
    "United States": (30, ["New York", "Austin", "Seattle", "Chicago", "Denver"]),
    "United Kingdom": (10, ["London", "Manchester", "Bristol"]),
    "Germany": (9, ["Berlin", "Munich", "Hamburg"]),
    "France": (8, ["Paris", "Lyon", "Marseille"]),
    "India": (12, ["Bengaluru", "Mumbai", "Delhi", "Chennai"]),
    "Canada": (7, ["Toronto", "Vancouver", "Montreal"]),
    "Australia": (6, ["Sydney", "Melbourne", "Perth"]),
    "Brazil": (6, ["Sao Paulo", "Rio de Janeiro"]),
    "Japan": (6, ["Tokyo", "Osaka"]),
    "Spain": (6, ["Madrid", "Barcelona"]),
}
SUPPLIER_COUNTRIES = ["China", "Japan", "Germany", "United States", "India", "Vietnam", "Mexico", "Italy"]
FIRST = ["Aarav", "Maya", "Liam", "Olivia", "Noah", "Emma", "Sofia", "Lucas", "Mia", "Ethan", "Isha", "Kenji",
         "Hana", "Mateo", "Lea", "Jonas", "Chloe", "Arjun", "Zoe", "Omar", "Nina", "Felix", "Priya", "Diego"]
LAST = ["Sharma", "Smith", "Johnson", "Garcia", "Muller", "Dubois", "Tanaka", "Silva", "Brown", "Patel",
        "Rossi", "Kim", "Lopez", "Nguyen", "Wilson", "Khan", "Fischer", "Costa", "Reddy", "Taylor"]
ADJ = ["Pro", "Max", "Lite", "Ultra", "Classic", "Eco", "Smart", "Prime", "Compact", "Deluxe"]
NOUN = {
    "Electronics": ["Headphones", "Charger", "Speaker", "Webcam", "Keyboard", "Monitor", "Router"],
    "Home & Kitchen": ["Blender", "Kettle", "Cookware Set", "Air Fryer", "Toaster", "Knife Set"],
    "Books": ["Novel", "Cookbook", "Biography", "Atlas", "Workbook", "Anthology"],
    "Clothing": ["Jacket", "T-Shirt", "Jeans", "Sneakers", "Hoodie", "Scarf"],
    "Sports & Outdoors": ["Yoga Mat", "Tent", "Backpack", "Dumbbell Set", "Bike Helmet"],
    "Beauty": ["Moisturizer", "Shampoo", "Serum", "Lip Balm", "Sunscreen"],
    "Toys & Games": ["Puzzle", "Board Game", "Building Set", "Plush Toy", "RC Car"],
    "Grocery": ["Coffee Beans", "Olive Oil", "Granola", "Green Tea", "Pasta Pack"],
    "Office Supplies": ["Notebook", "Desk Lamp", "Stapler", "Pen Set", "Planner"],
    "Garden": ["Planter", "Hose", "Pruner", "Seed Kit", "Garden Gloves"],
    "Automotive": ["Dash Cam", "Seat Cover", "Wiper Set", "Jump Starter", "Floor Mats"],
    "Pet Supplies": ["Dog Leash", "Cat Tree", "Pet Bed", "Chew Toy", "Feeder"],
}
PRICE_RANGE = {"Electronics": (20, 600), "Home & Kitchen": (12, 250), "Books": (6, 45), "Clothing": (10, 180),
               "Sports & Outdoors": (10, 300), "Beauty": (5, 90), "Toys & Games": (8, 80), "Grocery": (3, 40),
               "Office Supplies": (3, 70), "Garden": (6, 120), "Automotive": (10, 220), "Pet Supplies": (4, 90)}
CARRIERS = ["DHL", "FedEx", "UPS", "BlueDart", "Royal Mail"]
COMMENTS = ["Great value", "Works as described", "Not what I expected", "Would buy again", "Arrived late",
            "Excellent quality", "Poor packaging", "Okay for the price", None, None]


def rdate(rng: random.Random, lo: date, hi: date) -> date:
    return lo + timedelta(days=rng.randint(0, (hi - lo).days))


def seed(out: Path, seed_value: int = 42) -> dict:
    rng = random.Random(seed_value)
    if out.exists():
        out.unlink()
    con = sqlite3.connect(out)
    con.executescript((HERE / "schema.sql").read_text())

    con.executemany("INSERT INTO categories VALUES (?,?,NULL)", [(i + 1, n) for i, n in enumerate(CATEGORIES)])
    con.executemany(
        "INSERT INTO suppliers VALUES (?,?,?,?)",
        [(i + 1,
          f"{rng.choice(['Apex', 'Nova', 'Orion', 'Zenith', 'Atlas', 'Vertex'])} "
          f"{rng.choice(['Trading', 'Supply', 'Industries', 'Partners'])} {i + 1}",
          rng.choice(SUPPLIER_COUNTRIES), rng.randint(3, 30)) for i in range(40)])

    products = []
    for pid in range(1, 1001):
        cid = rng.randint(1, len(CATEGORIES))
        cname = CATEGORIES[cid - 1]
        lo, hi = PRICE_RANGE[cname]
        price = round(rng.uniform(lo, hi), 2)
        products.append((pid, f"{rng.choice(ADJ)} {rng.choice(NOUN[cname])} {pid}", cid, rng.randint(1, 40), price,
                         round(price * rng.uniform(0.4, 0.75), 2),
                         rdate(rng, date(2022, 6, 1), date(2025, 6, 30)).isoformat(),
                         0 if rng.random() < 0.08 else 1))
    con.executemany("INSERT INTO products VALUES (?,?,?,?,?,?,?,?)", products)

    names, weights = list(COUNTRIES), [COUNTRIES[c][0] for c in COUNTRIES]
    customers = []
    for cid in range(1, 1201):
        country = rng.choices(names, weights)[0]
        fn, ln = rng.choice(FIRST), rng.choice(LAST)
        signup = START + timedelta(days=int((rng.random() ** 1.6) * (AS_OF - START).days))
        customers.append((cid, fn, ln, f"{fn}.{ln}{cid}@example.com".lower(), country,
                          rng.choice(COUNTRIES[country][1]),
                          rng.choices(["Consumer", "Corporate", "Small Business"], [60, 15, 25])[0],
                          signup.isoformat()))
    con.executemany("INSERT INTO customers VALUES (?,?,?,?,?,?,?,?)", customers)
    signup_by_id = {c[0]: date.fromisoformat(c[7]) for c in customers}

    orders, items, payments, shipments = [], [], [], []
    item_id = pay_id = ship_id = 0
    span = (AS_OF - START).days
    for oid in range(1, 5001):
        cid = rng.randint(1, 1200)
        odate = START + timedelta(days=int((rng.random() ** 0.8) * span))  # mild growth over time
        odate = max(odate, signup_by_id[cid])
        age = (AS_OF - odate).days
        if age < 10:
            status = rng.choices(["pending", "shipped", "completed", "cancelled"], [40, 40, 10, 10])[0]
        elif age < 30:
            status = rng.choices(["shipped", "completed", "cancelled", "returned"], [20, 65, 10, 5])[0]
        else:
            status = rng.choices(["completed", "cancelled", "returned"], [86, 8, 6])[0]
        subtotal = 0.0
        for _ in range(rng.choices([1, 2, 3, 4, 5], [40, 28, 17, 10, 5])[0]):
            item_id += 1
            p = rng.choice(products)
            qty = rng.choices([1, 2, 3, 4], [60, 25, 10, 5])[0]
            disc = rng.choice([0, 0, 0, 0.05, 0.1, 0.15, 0.2, 0.3])
            line = round(qty * p[4] * (1 - disc), 2)
            subtotal += line
            items.append((item_id, oid, p[0], qty, p[4], disc, line))
        ship = round(rng.choice([0, 4.99, 6.99, 9.99]), 2)
        tax = round(subtotal * rng.choice([0.0, 0.05, 0.08, 0.1]), 2)
        total = round(subtotal + ship + tax, 2)
        orders.append((oid, cid, odate.isoformat(), status, ship, tax, total))

        if status != "pending":  # exactly one payment row per non-pending order
            pay_id += 1
            pstatus = {"cancelled": "failed", "returned": "refunded"}.get(status, "captured")
            payments.append((pay_id, oid, (odate + timedelta(days=rng.randint(0, 1))).isoformat(),
                             rng.choices(["credit_card", "paypal", "bank_transfer", "gift_card"], [55, 25, 12, 8])[0],
                             total, pstatus))
        if status in ("shipped", "completed", "returned"):
            ship_id += 1
            sdate = odate + timedelta(days=rng.randint(1, 3))
            if status == "shipped":
                delivered, sstat = None, "in_transit"
            else:
                delivered = sdate + timedelta(days=rng.randint(2, 9))
                sstat = "returned" if status == "returned" else "delivered"
                if delivered > AS_OF:
                    delivered, sstat = None, "in_transit"
            shipments.append((ship_id, oid, rng.choice(CARRIERS), sdate.isoformat(),
                              delivered.isoformat() if delivered else None, sstat))
    con.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?,?)", orders)
    con.executemany("INSERT INTO order_items VALUES (?,?,?,?,?,?,?)", items)
    con.executemany("INSERT INTO payments VALUES (?,?,?,?,?,?)", payments)
    con.executemany("INSERT INTO shipments VALUES (?,?,?,?,?,?)", shipments)

    reviews = []
    for rid in range(1, 3001):
        p = rng.choice(products)
        reviews.append((rid, p[0], rng.randint(1, 1200), rng.choices([1, 2, 3, 4, 5], [6, 8, 16, 32, 38])[0],
                        rdate(rng, max(date.fromisoformat(p[6]), START), AS_OF).isoformat(), rng.choice(COMMENTS)))
    con.executemany("INSERT INTO reviews VALUES (?,?,?,?,?,?)", reviews)
    con.commit()

    counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in
              ["categories", "suppliers", "products", "customers", "orders", "order_items", "payments",
               "shipments", "reviews"]}
    con.close()
    return counts


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "ecommerce.db"))
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    for table, n in seed(Path(a.out), a.seed).items():
        print(f"{table:12s} {n:>7,d}")
    print(f"\nWrote {a.out}")
