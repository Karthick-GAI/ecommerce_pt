#!/usr/bin/env python3
"""
generate_dataset.py — Synthetic E-Commerce Dataset Generator
=============================================================
Generates and loads into PostgreSQL (postgre_catalogue):

  products        5,000+  (pgvector embeddings via Azure OpenAI)
  customers      10,000
  orders         50,000   (cart_activity JSON, all status fields)
  browsing_events 150,000
  wishlists       30,000
  search_logs     15,000

All tables are created automatically. CSV files are written to ./data/

Usage:
    python3 generate_dataset.py                   # full run
    python3 generate_dataset.py --reset           # drop new tables, regenerate
    python3 generate_dataset.py --skip-embed      # skip Azure OpenAI step (fast test)
    python3 generate_dataset.py --csv             # also write CSVs to ./data/

Runtime (with embeddings): ~8-10 min
Runtime (--skip-embed):    ~2 min
"""

import argparse
import csv
import json
import math
import os
import random
import time
import uuid
from datetime import date, datetime, timedelta

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

DB_DSN = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/postgre_catalogue",
).replace("postgresql+psycopg2://", "postgresql://")

EXPORT_DIR = "./data"


def conn():
    c = psycopg2.connect(DB_DSN)
    psycopg2.extras.register_uuid(c)
    return c


# ═══════════════════════════════════════════════════════════════════════════════
#  DDL — new tables
# ═══════════════════════════════════════════════════════════════════════════════

DDL = """
CREATE TABLE IF NOT EXISTS customers (
    user_id         TEXT PRIMARY KEY,
    email           TEXT UNIQUE NOT NULL,
    first_name      TEXT NOT NULL,
    last_name       TEXT NOT NULL,
    phone           TEXT,
    city            TEXT,
    state           TEXT,
    pincode         TEXT,
    segment         TEXT,          -- budget | mid-range | premium
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS orders (
    order_id           TEXT PRIMARY KEY,
    user_id            TEXT REFERENCES customers(user_id) ON DELETE CASCADE,
    order_status       TEXT NOT NULL,   -- placed|confirmed|shipped|delivered|cancelled|returned
    payment_status     TEXT NOT NULL,   -- paid|pending|failed|refunded
    shipment_status    TEXT NOT NULL,   -- processing|dispatched|in_transit|delivered|failed
    total_amount       FLOAT NOT NULL,
    estimated_delivery DATE,
    cancellation_reason TEXT,
    cart_activity      JSONB NOT NULL,  -- [{product_id, quantity, unit_price}]
    created_at         TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_orders_user    ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_orders_status  ON orders(order_status);
CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at DESC);

CREATE TABLE IF NOT EXISTS browsing_events (
    id           TEXT PRIMARY KEY,
    user_id      TEXT REFERENCES customers(user_id) ON DELETE CASCADE,
    product_id   TEXT REFERENCES products(id) ON DELETE SET NULL,
    event_type   TEXT NOT NULL,    -- view|add_to_cart|wishlist|purchase
    session_id   TEXT,
    created_at   TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_events_user    ON browsing_events(user_id);
CREATE INDEX IF NOT EXISTS idx_events_product ON browsing_events(product_id);
CREATE INDEX IF NOT EXISTS idx_events_created ON browsing_events(created_at DESC);

CREATE TABLE IF NOT EXISTS wishlists (
    id          TEXT PRIMARY KEY,
    user_id     TEXT REFERENCES customers(user_id) ON DELETE CASCADE,
    product_id  TEXT REFERENCES products(id) ON DELETE CASCADE,
    created_at  TIMESTAMP DEFAULT NOW(),
    UNIQUE (user_id, product_id)
);

CREATE TABLE IF NOT EXISTS search_logs (
    id                 TEXT PRIMARY KEY,
    user_id            TEXT REFERENCES customers(user_id) ON DELETE SET NULL,
    query              TEXT NOT NULL,
    results_count      INT DEFAULT 0,
    clicked_product_id TEXT REFERENCES products(id) ON DELETE SET NULL,
    search_type        TEXT DEFAULT 'keyword',   -- keyword | semantic
    created_at         TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_search_user    ON search_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_search_created ON search_logs(created_at DESC);
"""

DROP_TABLES = """
DROP TABLE IF EXISTS search_logs    CASCADE;
DROP TABLE IF EXISTS wishlists      CASCADE;
DROP TABLE IF EXISTS browsing_events CASCADE;
DROP TABLE IF EXISTS orders         CASCADE;
DROP TABLE IF EXISTS customers      CASCADE;
DROP TABLE IF EXISTS reviews        CASCADE;
DROP TABLE IF EXISTS product_images CASCADE;
DROP TABLE IF EXISTS products       CASCADE;
DROP TABLE IF EXISTS categories     CASCADE;
"""


# ═══════════════════════════════════════════════════════════════════════════════
#  PRODUCT TEMPLATES  (name_template, description, category, subcategory,
#                      brand, base_price, variants[{key: val, …}], tags)
# ═══════════════════════════════════════════════════════════════════════════════

def _v(*items):
    """Cartesian-product helper — returns list of dicts from positional arg lists."""
    import itertools
    keys = [k for k, _ in items]
    vals = [v for _, v in items]
    return [dict(zip(keys, combo)) for combo in itertools.product(*vals)]


PRODUCT_TEMPLATES = []


def _add(name_tpl, desc_tpl, cat, subcat, brand, base_price, variants, tags, spec_base=None):
    PRODUCT_TEMPLATES.append((name_tpl, desc_tpl, cat, subcat, brand,
                               float(base_price), variants, tags, spec_base or {}))


# ── ELECTRONICS / LAPTOP ──────────────────────────────────────────────────────

for _brand, _model, _chip_list, _price in [
    ("Apple", "MacBook Air",
     [("M1", 0.75), ("M2", 1.0), ("M3", 1.20)], 79990),
    ("Apple", "MacBook Pro 14-inch",
     [("M3", 1.0), ("M3 Pro", 1.35), ("M3 Max", 1.80)], 149990),
    ("Apple", "MacBook Pro 16-inch",
     [("M3 Pro", 1.0), ("M3 Max", 1.50)], 199990),
]:
    for _chip, _mult in _chip_list:
        for _ram, _storage, _smul in [
            ("8GB", "256GB SSD", 1.0), ("8GB", "512GB SSD", 1.12),
            ("16GB", "512GB SSD", 1.25), ("16GB", "1TB SSD", 1.40),
            ("32GB", "1TB SSD", 1.65),
        ]:
            _name = f"{_brand} {_model} {_chip} {_ram} {_storage}"
            _desc = (f"The {_brand} {_model} powered by the {_chip} chip delivers "
                     f"extraordinary performance with {_ram} unified memory and {_storage}. "
                     f"Ideal for students, developers, and creative professionals who demand speed.")
            _specs = {"Chip": _chip, "RAM": _ram, "Storage": _storage,
                      "Display": "Liquid Retina", "Battery": "18-22 hr"}
            _tags = ["macOS", "Apple", "laptop", "ultrabook", _chip.replace(" ", "-").lower()]
            PRODUCT_TEMPLATES.append(
                (_name, _desc, "Electronics", "Laptop", _brand,
                 round(_price * _mult * _smul, -2),
                 [{"Color": c} for c in ["Space Gray", "Silver", "Midnight"]],
                 _tags, _specs)
            )

for _brand, _model, _proc_list, _base_price in [
    ("Dell", "XPS 13", [("i5-1335U", 1.0), ("i7-1355U", 1.20), ("i7-13700H", 1.40)], 85990),
    ("Dell", "XPS 15", [("i7-13700H", 1.0), ("i9-13900H", 1.35)], 120990),
    ("Dell", "Inspiron 15",  [("Ryzen 5 5500U", 1.0), ("i5-1235U", 1.10)], 44990),
    ("HP",   "Spectre x360", [("i5-1335U", 1.0), ("i7-1355U", 1.30)], 89990),
    ("HP",   "Envy x360",    [("Ryzen 5 7530U", 1.0), ("i5-1335U", 1.15)], 74990),
    ("HP",   "Pavilion 15",  [("Ryzen 5 5500U", 1.0), ("i5-1235U", 1.10)], 44990),
    ("Lenovo", "ThinkPad X1 Carbon", [("i5-1345U", 1.0), ("i7-1365U", 1.30), ("i7 vPro", 1.50)], 99990),
    ("Lenovo", "IdeaPad Slim 5",     [("i5-1335U", 1.0), ("Ryzen 5 7530U", 0.95)], 49990),
    ("Lenovo", "Legion 5 Gen 8",     [("Ryzen 7 7745HX", 1.0), ("Ryzen 9 7945HX", 1.30)], 79990),
    ("Asus",   "ZenBook 14",         [("Ryzen 5 7530U", 1.0), ("i5-1340P", 1.10)], 59990),
    ("Asus",   "VivoBook 16X",       [("Ryzen 7 7730U", 1.0), ("i5-12500H", 0.95)], 64990),
    ("Asus",   "ROG Strix G15",      [("Ryzen 7 7745HX", 1.0), ("Ryzen 9 7945HX", 1.25)], 99990),
    ("Acer",   "Aspire 5",           [("Ryzen 5 5500U", 1.0), ("i5-1235U", 1.10)], 39990),
    ("Acer",   "Nitro 5 Gaming",     [("Ryzen 5 7535H", 1.0), ("i5-12500H", 1.10)], 59990),
    ("MSI",    "Modern 15",          [("Ryzen 5 5625U", 1.0), ("i5-1155G7", 1.05)], 49990),
    ("Samsung","Galaxy Book4 Pro",   [("i5-1335U", 1.0), ("i7-1355U", 1.30)], 89990),
    ("Microsoft", "Surface Laptop 5",[("i5-1245U", 1.0), ("i7-1265U", 1.30)], 99990),
]:
    for _proc, _pmul in _proc_list:
        for _ram, _stor, _smul in [
            ("8GB", "256GB SSD", 1.0), ("8GB", "512GB SSD", 1.10),
            ("16GB", "512GB SSD", 1.22), ("16GB", "1TB SSD", 1.35),
        ]:
            _name = f"{_brand} {_model} {_proc} {_ram} {_stor}"
            _desc = (f"The {_brand} {_model} with {_proc} processor and {_ram} RAM delivers "
                     f"outstanding performance for work and study. {_stor} storage for all your files.")
            _specs = {"Processor": _proc, "RAM": _ram, "Storage": _stor}
            _tags = ["laptop", "Windows", _brand.lower(), _proc.split("-")[0].lower()]
            PRODUCT_TEMPLATES.append(
                (_name, _desc, "Electronics", "Laptop", _brand,
                 round(_base_price * _pmul * _smul, -2),
                 [{"Color": c} for c in ["Black", "Silver"]],
                 _tags, _specs)
            )

# ── ELECTRONICS / SMARTPHONE ──────────────────────────────────────────────────

for _brand, _model, _chip, _cam, _base_price, _storage_list in [
    ("Apple", "iPhone 15",      "A16 Bionic", "48MP", 69990,  ["128GB", "256GB", "512GB"]),
    ("Apple", "iPhone 15 Plus", "A16 Bionic", "48MP", 79990,  ["128GB", "256GB", "512GB"]),
    ("Apple", "iPhone 15 Pro",  "A17 Pro",    "48MP ProRAW", 129990, ["128GB", "256GB", "512GB", "1TB"]),
    ("Apple", "iPhone 14",      "A15 Bionic", "12MP", 59990,  ["128GB", "256GB"]),
    ("Samsung", "Galaxy S24",        "Snapdragon 8 Gen 3", "50MP",  74999, ["128GB", "256GB"]),
    ("Samsung", "Galaxy S24+",       "Snapdragon 8 Gen 3", "50MP",  94999, ["256GB", "512GB"]),
    ("Samsung", "Galaxy S24 Ultra",  "Snapdragon 8 Gen 3", "200MP", 124999,["256GB", "512GB", "1TB"]),
    ("Samsung", "Galaxy A55 5G",     "Exynos 1480",        "50MP",  34999, ["128GB", "256GB"]),
    ("Samsung", "Galaxy A35 5G",     "Exynos 1380",        "50MP",  24999, ["128GB", "256GB"]),
    ("OnePlus", "12R",     "Snapdragon 8 Gen 1", "50MP Sony", 39999, ["128GB", "256GB"]),
    ("OnePlus", "12",      "Snapdragon 8 Gen 3", "50MP Hasselblad", 64999, ["256GB", "512GB"]),
    ("OnePlus", "Nord CE 4", "Snapdragon 7s Gen 2", "50MP", 24999, ["128GB", "256GB"]),
    ("Redmi",   "Note 13 Pro 5G",    "Dimensity 7200-Ultra", "200MP", 29999, ["128GB", "256GB"]),
    ("Redmi",   "Note 13 5G",        "Snapdragon 7s Gen 2",  "108MP", 19999, ["128GB", "256GB"]),
    ("Redmi",   "13C",               "Helio G85",            "50MP",  9999,  ["128GB", "256GB"]),
    ("Realme",  "Narzo 60 Pro 5G",   "Dimensity 7050",       "100MP", 19999, ["128GB", "256GB"]),
    ("Realme",  "12 Pro+ 5G",        "Snapdragon 7s Gen 2",  "50MP Periscope", 26999, ["128GB", "256GB"]),
    ("Vivo",    "V29 5G",            "Snapdragon 778G",      "50MP Aura Light", 33999, ["128GB", "256GB"]),
    ("OPPO",    "Reno 11 5G",        "Dimensity 7050",       "50MP", 29999, ["128GB", "256GB"]),
    ("OPPO",    "Find X7 Pro",       "Dimensity 9300",       "50MP Hasselblad", 79999, ["256GB", "512GB"]),
]:
    for _stor in _storage_list:
        for _color in ["Black", "Blue", "Green", "White"]:
            _name = f"{_brand} {_model} {_stor} {_color}"
            _desc = (f"The {_brand} {_model} features the powerful {_chip} processor, "
                     f"{_cam} main camera, and {_stor} storage. "
                     f"Experience blazing-fast 5G connectivity and all-day battery life.")
            _specs = {"Processor": _chip, "Storage": _stor, "Camera": _cam, "5G": "Yes", "Color": _color}
            _tags = ["5G", "smartphone", _brand.lower(), "AMOLED", "fast charging"]
            PRODUCT_TEMPLATES.append(
                (_name, _desc, "Electronics", "Smartphone", _brand,
                 round(_base_price * (1 + _storage_list.index(_stor) * 0.12), -2),
                 [{}], _tags, _specs)
            )

# ── ELECTRONICS / HEADPHONES ──────────────────────────────────────────────────

for _brand, _model, _type, _feat, _price in [
    ("Sony",       "WH-1000XM5",   "Over-ear",  "Industry-leading ANC, 30hr battery, multipoint BT", 26990),
    ("Sony",       "WH-1000XM4",   "Over-ear",  "LDAC hi-res audio, ANC, 30hr battery",              19990),
    ("Sony",       "WF-1000XM5",   "In-ear TWS","ANC TWS earbuds, LDAC, 8hr+24hr battery",            19990),
    ("Bose",       "QuietComfort 45","Over-ear", "Balanced sound, ANC, 24hr battery",                  24990),
    ("Bose",       "QuietComfort Earbuds II","In-ear TWS","ANC TWS, CustomTune, 6hr+18hr", 24990),
    ("JBL",        "Tune 760NC",   "Over-ear",  "ANC, 35hr battery, foldable, affordable",             7999),
    ("JBL",        "Free X TWS",   "In-ear TWS","TWS earbuds, 4hr+28hr, IPX5 waterproof",              4999),
    ("Sennheiser", "HD 599",       "Over-ear open-back", "Natural soundstage, audiophile grade", 11990),
    ("Sennheiser", "Momentum 4",   "Over-ear",  "ANC, 60hr battery, pristine audio quality",           26990),
    ("Boat",       "Rockerz 450 Pro","Over-ear","40hr battery, 40mm driver, foldable, bass boost",     1999),
    ("Boat",       "Airdopes 141", "In-ear TWS","TWS, 42hr total battery, ENx noise cancellation",     1299),
    ("Skullcandy", "Crusher ANC 2","Over-ear",  "Adjustable sensory bass, ANC, 50hr battery",          14990),
    ("Apple",      "AirPods 3",    "In-ear",    "Adaptive EQ, spatial audio, 6hr+30hr battery",        17900),
    ("Apple",      "AirPods Pro 2","In-ear TWS","ANC, Transparency mode, Adaptive Audio",               24900),
    ("Samsung",    "Galaxy Buds2 Pro","In-ear TWS","24bit Hi-Fi ANC, 5hr+13hr, IPX7",                   11999),
]:
    for _color in ["Black", "White", "Blue"]:
        _name = f"{_brand} {_model} {_color}"
        _desc = (f"The {_brand} {_model} {_type} headphone — {_feat}. "
                 f"Available in {_color}, perfect for commuters, professionals, and audiophiles.")
        _specs = {"Type": _type, "Color": _color, "Brand": _brand}
        _tags = ["headphones", "audio", _brand.lower(), _type.split()[0].lower()]
        PRODUCT_TEMPLATES.append(
            (_name, _desc, "Electronics", "Headphones & Earphones", _brand,
             _price, [{}], _tags, _specs)
        )

# ── ELECTRONICS / SMART TV ────────────────────────────────────────────────────

for _brand, _series, _res, _price_32 in [
    ("Samsung", "Crystal 4K UHD",   "4K", 28990),
    ("Samsung", "QLED Q60C",        "4K QLED", 49990),
    ("LG",      "UHD UR7500",       "4K", 27990),
    ("LG",      "OLED C3",          "4K OLED", 89990),
    ("Sony",    "Bravia X75L",      "4K", 39990),
    ("Mi",      "5X Series",        "4K", 22990),
    ("OnePlus", "Y1S Pro",          "4K", 24990),
    ("Vu",      "Masterpiece OLED", "4K OLED", 79990),
]:
    for _size, _mul in [("32-inch", 0.55), ("43-inch", 0.80), ("55-inch", 1.0),
                        ("65-inch", 1.50), ("75-inch", 2.20)]:
        _name = f"{_brand} {_series} {_size} {_res} Smart TV"
        _desc = (f"The {_brand} {_series} {_size} Smart TV delivers stunning {_res} picture quality. "
                 f"Enjoy your favourite streaming apps, smart home control, and crystal-clear visuals.")
        _specs = {"Screen Size": _size, "Resolution": _res, "Smart OS": "Android TV", "HDR": "Yes"}
        _tags = ["TV", "smart TV", "4K", _brand.lower(), "streaming"]
        PRODUCT_TEMPLATES.append(
            (_name, _desc, "Electronics", "Smart TV", _brand,
             round(_price_32 * _mul, -2), [{}], _tags, _specs)
        )

# ── ELECTRONICS / TABLETS ─────────────────────────────────────────────────────

for _brand, _model, _chip, _base_price in [
    ("Apple",   "iPad 10th Gen", "A14 Bionic", 44900),
    ("Apple",   "iPad Air M1",   "Apple M1",   54900),
    ("Apple",   "iPad Pro M4",   "Apple M4",   84900),
    ("Samsung", "Galaxy Tab S9 FE", "Exynos 1380", 44999),
    ("Samsung", "Galaxy Tab S9",    "Snapdragon 8 Gen 2", 72999),
    ("Lenovo",  "Tab P12 Pro",      "Snapdragon 870", 49990),
    ("OnePlus", "Pad Go",           "Helio G99", 19999),
]:
    for _stor, _smul in [("64GB", 1.0), ("128GB", 1.15), ("256GB", 1.35)]:
        for _conn in ["Wi-Fi", "Wi-Fi + Cellular"]:
            _name = f"{_brand} {_model} {_stor} {_conn}"
            _desc = (f"{_brand} {_model} powered by {_chip}. {_stor} storage, "
                     f"{_conn} connectivity. Perfect for learning, entertainment, and productivity.")
            _specs = {"Chip": _chip, "Storage": _stor, "Connectivity": _conn}
            _tags = ["tablet", "iPad", _brand.lower(), "portable", "education"]
            PRODUCT_TEMPLATES.append(
                (_name, _desc, "Electronics", "Tablet", _brand,
                 round(_base_price * _smul * (1.15 if _conn == "Wi-Fi + Cellular" else 1.0), -2),
                 [{}], _tags, _specs)
            )

# ── CLOTHING / MEN'S T-SHIRTS ─────────────────────────────────────────────────

_tshirt_designs = [
    ("Dri-FIT Training",    "moisture-wicking polyester, keeps you dry during intense workouts",
     "Nike",   1299, ["gym", "sport", "dri-fit", "training"]),
    ("Essentials 3-Stripes","cotton blend casual tee with iconic 3-stripes design",
     "Adidas", 999,  ["casual", "classic", "cotton", "everyday"]),
    ("Graphic Crew",        "premium 100% cotton with iconic logo, relaxed fit",
     "Levi's", 1499, ["cotton", "graphic", "logo", "casual"]),
    ("DryCELL Performance", "slim fit technical fabric, great for sports and gym",
     "Puma",   799,  ["gym", "slim", "sport", "moisture-wicking"]),
    ("UA Tech 2.0",         "ultra-soft anti-odour fabric, HeatGear technology",
     "Under Armour", 1599, ["sport", "anti-odour", "HeatGear", "gym"]),
    ("HeatGear Compression","compression fit, moisture transport, 4-way stretch",
     "Under Armour", 1899, ["compression", "gym", "stretch", "performance"]),
    ("Supima Cotton Crew",  "premium Supima cotton, superior softness and durability",
     "Tommy Hilfiger", 1999, ["premium", "cotton", "casual", "brand"]),
    ("Classic Polo",        "pique cotton polo shirt, versatile for casual and semi-formal",
     "Lacoste", 3499, ["polo", "semi-formal", "cotton", "classic"]),
]

for _design, _desc_detail, _brand, _price, _tags in _tshirt_designs:
    for _size in ["XS", "S", "M", "L", "XL", "XXL"]:
        for _color in ["Black", "White", "Navy", "Grey", "Red"]:
            _name = f"{_brand} Men's {_design} T-Shirt {_color} {_size}"
            _desc = (f"The {_brand} Men's {_design} T-Shirt in {_color}. "
                     f"Made from {_desc_detail}. Size {_size}.")
            _specs = {"Brand": _brand, "Size": _size, "Color": _color, "Gender": "Men"}
            PRODUCT_TEMPLATES.append(
                (_name, _desc, "Clothing", "Men's T-Shirts", _brand,
                 _price, [{}], _tags + ["men", _size.lower()], _specs)
            )

# ── CLOTHING / WOMEN'S KURTAS ─────────────────────────────────────────────────

_kurta_info = [
    ("Printed A-Line",  "vibrant traditional print, A-line silhouette",     "Biba",       1299),
    ("Embroidered Anarkali","intricate embroidery, floor-length festive look","W",          2499),
    ("Solid Straight",  "minimalist solid colour, straight cut for office",  "Libas",      1199),
    ("Bandhani Print",  "authentic Bandhani block print, festive wear",      "Jaipur Kurti",1599),
    ("Chikankari",      "delicate Lucknowi chikankari embroidery, white",    "Fabindia",   2999),
    ("Digital Print",   "contemporary digital print, modern fusion style",   "AND",        1799),
    ("Floral Cotton",   "breathable cotton, relaxed fit, daily wear",        "Global Desi",1099),
]

for _style, _desc_detail, _brand, _price in _kurta_info:
    for _size in ["XS", "S", "M", "L", "XL", "XXL"]:
        for _color in ["Blue", "Green", "Pink", "Yellow", "White", "Red"]:
            _name = f"{_brand} Women's {_style} Kurta {_color} {_size}"
            _desc = (f"{_brand} Women's {_style} Kurta in {_color}. "
                     f"Features {_desc_detail}. Comfortable size {_size}.")
            _specs = {"Brand": _brand, "Size": _size, "Color": _color, "Gender": "Women"}
            _tags = ["kurta", "ethnic", "women", "Indian", _brand.lower()]
            PRODUCT_TEMPLATES.append(
                (_name, _desc, "Clothing", "Women's Kurtas", _brand,
                 _price, [{}], _tags, _specs)
            )

# ── HOME & KITCHEN / AIR FRYER ────────────────────────────────────────────────

for _brand, _model, _power, _base_price in [
    ("Philips",    "Essential HD9200",  "1400W", 7999),
    ("Philips",    "Viva HD9252",       "1400W", 9999),
    ("Inalsa",     "Nutri Fry",         "1400W", 3499),
    ("Wonderchef", "Prato Digital",     "1500W", 4499),
    ("Havells",    "Prolife Digi",      "1230W", 5999),
    ("Prestige",   "PAF 6.0",           "1700W", 5499),
    ("Bajaj",      "Fry Maestro",       "1200W", 3299),
    ("Lifelong",   "Digital Air Fryer", "1400W", 2999),
]:
    for _cap, _cmul in [
        ("2.5L", 0.80), ("3.5L", 0.90), ("4L", 1.0),
        ("5L", 1.15), ("6L", 1.30), ("7L", 1.50),
    ]:
        _name = f"{_brand} {_model} {_cap} Air Fryer"
        _desc = (f"The {_brand} {_model} {_cap} Air Fryer uses Rapid Air Technology to fry, "
                 f"bake, roast and grill with up to 90% less oil. {_power} powerful motor.")
        _specs = {"Capacity": _cap, "Power": _power, "Brand": _brand}
        _tags = ["air fryer", "healthy", "kitchen", "low fat", _brand.lower()]
        PRODUCT_TEMPLATES.append(
            (_name, _desc, "Home & Kitchen", "Air Fryer", _brand,
             round(_base_price * _cmul, -2), [{}], _tags, _specs)
        )

# ── HOME & KITCHEN / WASHING MACHINE ──────────────────────────────────────────

for _brand, _type, _base_price in [
    ("LG",       "Front Load",     35990),
    ("Samsung",  "Front Load",     34990),
    ("Whirlpool","Top Load",       18990),
    ("Bosch",    "Front Load",     44990),
    ("IFB",      "Front Load",     32990),
    ("Haier",    "Top Load",       14990),
]:
    for _cap, _mul in [
        ("6kg", 0.85), ("7kg", 0.95), ("8kg", 1.0),
        ("9kg", 1.12), ("10kg", 1.25),
    ]:
        _name = f"{_brand} {_cap} {_type} Washing Machine"
        _desc = (f"The {_brand} {_cap} {_type} Washing Machine offers "
                 f"energy-efficient wash cycles, multiple programmes, and reliable performance for daily use.")
        _specs = {"Capacity": _cap, "Type": _type, "Energy Rating": "5 Star"}
        _tags = ["washing machine", "home appliance", _brand.lower(), _type.lower()]
        PRODUCT_TEMPLATES.append(
            (_name, _desc, "Home & Kitchen", "Washing Machine", _brand,
             round(_base_price * _mul, -2), [{}], _tags, _specs)
        )

# ── SPORTS & FITNESS / PROTEIN POWDER ────────────────────────────────────────

for _brand, _type, _base_price in [
    ("MuscleBlaze",         "Whey Protein",          1999),
    ("Optimum Nutrition",   "Gold Standard Whey",    3499),
    ("MyProtein",           "Impact Whey Protein",   2499),
    ("AS-IT-IS",            "Whey Protein Isolate",  2299),
    ("Dymatize",            "ISO100 Whey Isolate",   3999),
    ("GNC",                 "Pro Performance Whey",  2799),
    ("Healthkart",          "HK Vitals Whey",        1799),
]:
    for _flavour in ["Chocolate", "Vanilla", "Strawberry", "Cookies & Cream",
                     "Mango", "Unflavoured", "Cafe Mocha", "Banana"]:
        for _size, _mul in [("500g", 0.55), ("1kg", 1.0), ("2kg", 1.85), ("4.5kg", 3.80)]:
            _name = f"{_brand} {_type} {_flavour} {_size}"
            _desc = (f"{_brand} {_type} in {_flavour} flavour. {_size} pack with 24g protein "
                     f"per serving, 5.5g BCAA, and 4g glutamine. Ideal post-workout nutrition.")
            _specs = {"Protein/serving": "24g", "BCAA": "5.5g", "Flavour": _flavour, "Weight": _size}
            _tags = ["protein", "whey", "gym", "supplement", _flavour.lower()]
            PRODUCT_TEMPLATES.append(
                (_name, _desc, "Sports & Fitness", "Protein Powder", _brand,
                 round(_base_price * _mul, -2), [{}], _tags, _specs)
            )

# ── BEAUTY / SKINCARE ─────────────────────────────────────────────────────────

for _brand, _product, _desc_detail, _price in [
    ("Minimalist", "Niacinamide 10% + Zinc Serum 30ml",
     "reduces blemishes, controls oil, brightens skin", 599),
    ("Minimalist", "Vitamin C 10% Face Serum 30ml",
     "brightens complexion, reduces dark spots, antioxidant protection", 699),
    ("The Ordinary", "Hyaluronic Acid 2% + B5 30ml",
     "deep hydration, plumps skin, improves texture", 799),
    ("Dot & Key",   "Vitamin C + E Moisturiser SPF 25 50g",
     "brightening moisturiser with SPF protection", 699),
    ("Plum",        "Green Tea Renewed Clarity Night Gel 50ml",
     "fights acne overnight, green tea antioxidants", 499),
    ("Biotique",    "Bio Papaya Scrub 75g",
     "exfoliates dead skin cells, brightens complexion naturally", 179),
    ("Mamaearth",   "Ubtan Face Wash 100ml",
     "natural turmeric and saffron, brightening face wash", 249),
    ("WOW Skin Science","Apple Cider Vinegar Face Wash 100ml",
     "deep cleanses pores, removes excess oil, clarifying", 349),
    ("Cetaphil",    "Moisturising Lotion 250ml",
     "non-greasy, fragrance-free, dermatologist recommended", 649),
    ("Neutrogena",  "Hydro Boost Gel Cream 47ml",
     "water-gel texture, hyaluronic acid, 48-hour hydration", 899),
]:
    for _skin_type in ["Oily", "Dry", "Combination", "Sensitive", "All Skin Types"]:
        _name = f"{_brand} {_product} — {_skin_type}"
        _desc = (f"{_brand} {_product}: {_desc_detail}. "
                 f"Formulated for {_skin_type} skin. Dermatologist tested, paraben-free.")
        _specs = {"Brand": _brand, "Skin Type": _skin_type, "Size": _product.split()[-1]}
        _tags = ["skincare", "beauty", _brand.lower(), "face", _skin_type.lower().replace(" ", "-")]
        PRODUCT_TEMPLATES.append(
            (_name, _desc, "Beauty", "Skincare", _brand, _price,
             [{}], _tags, _specs)
        )

# ── BEAUTY / HAIRCARE ─────────────────────────────────────────────────────────

for _brand, _line, _desc_detail, _price in [
    ("Dove", "Intense Repair Shampoo", "repairs damaged hair, keratin actives", 299),
    ("Dove", "Intense Repair Conditioner", "deep conditioning, reduces breakage", 259),
    ("Pantene", "Long Black Shampoo", "strengthens from root to tip", 349),
    ("Tresemme", "Keratin Smooth Shampoo", "keratin infused, frizz control for 72hr", 399),
    ("L'Oreal", "Total Repair 5 Shampoo", "repairs 5 signs of damaged hair", 449),
    ("Mamaearth", "Onion Shampoo", "reduces hairfall, onion seed oil", 349),
    ("WOW Apple Cider Vinegar Shampoo", "clarifying shampoo, removes buildup", "scalp detox", 449),
    ("Indulekha", "Bringha Hair Oil", "reduces hairfall, promotes growth", 399),
    ("Parachute", "Advansed Jasmine Hair Oil", "nourishes scalp, jasmine fragrance", 199),
    ("Himalaya", "Anti-Hairfall Shampoo", "reduces hairfall, bhringraj and palasha", 199),
]:
    for _size in ["100ml", "200ml", "400ml", "650ml"]:
        _name = f"{_brand} {_line} {_size}"
        _desc = (f"{_brand} {_line} — {_desc_detail}. "
                 f"{_size} pack for regular use. Suitable for Indian hair types.")
        _specs = {"Brand": _brand, "Size": _size}
        _tags = ["haircare", "hair", _brand.lower(), "beauty", "scalp"]
        PRODUCT_TEMPLATES.append(
            (_name, _desc, "Beauty", "Haircare", _brand, _price,
             [{}], _tags, _specs)
        )

# ── BOOKS ─────────────────────────────────────────────────────────────────────

BOOKS = [
    ("Atomic Habits", "James Clear", "Self-Help",
     "Tiny changes, remarkable results. Build good habits and break bad ones with a proven framework.",
     499, ["habits", "productivity", "self-improvement", "bestseller"]),
    ("Rich Dad Poor Dad", "Robert Kiyosaki", "Finance",
     "The classic financial literacy book. Learn to make money work for you.",
     399, ["finance", "money", "investment", "classic"]),
    ("The Psychology of Money", "Morgan Housel", "Finance",
     "Timeless lessons on wealth, greed, and happiness. How people think about money.",
     449, ["finance", "psychology", "money", "investing"]),
    ("Deep Work", "Cal Newport", "Self-Help",
     "Rules for focused success in a distracted world. Produce your best work.",
     399, ["productivity", "focus", "career", "success"]),
    ("The Alchemist", "Paulo Coelho", "Fiction",
     "A magical story about following your dreams. Over 65 million copies sold.",
     250, ["fiction", "inspirational", "classic", "adventure"]),
    ("Ikigai", "Hector Garcia", "Self-Help",
     "The Japanese secret to a long and happy life — finding your reason for being.",
     299, ["Japanese", "life purpose", "happiness", "philosophy"]),
    ("Zero to One", "Peter Thiel", "Business",
     "How to build a company that creates something new. Essential for entrepreneurs.",
     499, ["business", "startup", "entrepreneurship", "innovation"]),
    ("Thinking Fast and Slow", "Daniel Kahneman", "Psychology",
     "Two systems that drive the way we think. A Nobel Prize winner's masterwork.",
     599, ["psychology", "decision making", "cognitive bias", "Nobel"]),
    ("Sapiens", "Yuval Noah Harari", "History",
     "A brief history of humankind. How Homo sapiens came to dominate the world.",
     549, ["history", "anthropology", "evolution", "bestseller"]),
    ("The Lean Startup", "Eric Ries", "Business",
     "How continuous innovation creates radically successful businesses.",
     499, ["startup", "lean", "entrepreneurship", "agile"]),
    ("Start With Why", "Simon Sinek", "Business",
     "How great leaders inspire everyone to take action. The Golden Circle framework.",
     399, ["leadership", "business", "motivation", "strategy"]),
    ("Can't Hurt Me", "David Goggins", "Self-Help",
     "Master your mind and defy the odds. Navy SEAL shares his extraordinary life story.",
     449, ["motivation", "mental strength", "autobiography", "fitness"]),
    ("The 4-Hour Workweek", "Tim Ferriss", "Self-Help",
     "Escape 9-5, live anywhere, and join the new rich. Work smarter, not harder.",
     399, ["productivity", "lifestyle", "entrepreneurship", "travel"]),
    ("Good to Great", "Jim Collins", "Business",
     "Why some companies make the leap and others don't. Research-backed business insights.",
     549, ["business", "leadership", "strategy", "management"]),
    ("The Intelligent Investor", "Benjamin Graham", "Finance",
     "The definitive book on value investing. Warren Buffett's favourite book.",
     599, ["investing", "value investing", "finance", "stock market"]),
    ("Educated", "Tara Westover", "Memoir",
     "A memoir about a girl who grows up in a survivalist family and educates herself.",
     399, ["memoir", "education", "inspiration", "biography"]),
    ("The Midnight Library", "Matt Haig", "Fiction",
     "A library that contains infinite books, each telling the story of another life you could have lived.",
     349, ["fiction", "fantasy", "philosophical", "contemporary"]),
    ("Norwegian Wood", "Haruki Murakami", "Fiction",
     "A deeply moving story of loss, love, and the perils of growing up.",
     299, ["fiction", "Japanese", "literary", "romance"]),
    ("The Silent Patient", "Alex Michaelides", "Thriller",
     "A famous painter shoots her husband and then never speaks another word.",
     349, ["thriller", "mystery", "psychological", "bestseller"]),
    ("Where the Crawdads Sing", "Delia Owens", "Fiction",
     "A murder mystery set in the marshes of North Carolina. A wild child teaches herself.",
     399, ["fiction", "mystery", "nature", "bestseller"]),
    ("The Subtle Art of Not Giving a F*ck", "Mark Manson", "Self-Help",
     "A counterintuitive approach to living a good life by focusing on what truly matters.",
     399, ["self-help", "mindset", "philosophy", "bestseller"]),
    ("Dune", "Frank Herbert", "Sci-Fi",
     "The classic epic of politics, religion, ecology, and revenge in a far-future universe.",
     499, ["sci-fi", "epic", "fantasy", "classic"]),
    ("Harry Potter and the Philosopher's Stone", "J.K. Rowling", "Fiction",
     "A young boy discovers he's a wizard and enters the magical world of Hogwarts.",
     399, ["fiction", "fantasy", "magic", "Harry Potter"]),
    ("The Great Gatsby", "F. Scott Fitzgerald", "Fiction",
     "The story of Jay Gatsby's obsessive love for Daisy Buchanan in Jazz Age America.",
     299, ["classic", "fiction", "American literature", "romance"]),
    ("Freakonomics", "Steven D. Levitt & Stephen J. Dubner", "Non-Fiction",
     "A rogue economist explores the hidden side of everything.",
     349, ["economics", "non-fiction", "data", "social science"]),
    ("Clean Code", "Robert C. Martin", "Technology",
     "A handbook of agile software craftsmanship. Write clean, maintainable code.",
     699, ["programming", "software", "clean code", "agile"]),
    ("The Pragmatic Programmer", "Andrew Hunt", "Technology",
     "Your journey to mastery. Tips and best practices from experienced developers.",
     649, ["programming", "software engineering", "best practices", "career"]),
    ("Designing Data-Intensive Applications", "Martin Kleppmann", "Technology",
     "The big ideas behind reliable, scalable, and maintainable systems.",
     899, ["databases", "distributed systems", "engineering", "architecture"]),
    ("You Don't Know JS", "Kyle Simpson", "Technology",
     "Deep dive into the core mechanisms of JavaScript. For serious JS developers.",
     599, ["JavaScript", "programming", "web development", "frontend"]),
    ("The Hitchhiker's Guide to the Galaxy", "Douglas Adams", "Sci-Fi",
     "Don't panic. A wildly imaginative comedy about life, the universe, and everything.",
     299, ["sci-fi", "comedy", "classic", "humour"]),
]

for _title, _author, _genre, _desc, _price, _tags in BOOKS:
    for _format, _fmul in [("Paperback", 1.0), ("Hardcover", 1.5), ("Kindle Edition", 0.6)]:
        _name = f"{_title} by {_author} ({_format})"
        _full_desc = f"{_desc} Author: {_author}. Genre: {_genre}. Format: {_format}."
        _specs = {"Author": _author, "Genre": _genre, "Format": _format, "Language": "English"}
        PRODUCT_TEMPLATES.append(
            (_name, _full_desc, "Books", _genre, _author.split()[0], round(_price * _fmul),
             [{}], _tags + ["book", _format.lower(), _genre.lower()], _specs)
        )

# ── GROCERIES & FMCG ──────────────────────────────────────────────────────────

GROCERY_ITEMS = [
    ("Fortune Sunflower Oil",   "Grocery", "Cooking Oil",    "Fortune", 149,  ["cooking oil", "sunflower", "healthy"], "refined sunflower oil, light and healthy for daily cooking"),
    ("Saffola Gold Blended Oil","Grocery", "Cooking Oil",    "Saffola", 299,  ["cooking oil", "blended", "heart health"], "blend of rice bran and corn oil, good for heart health"),
    ("MDH Chaat Masala",        "Grocery", "Spices",         "MDH",     99,   ["spice", "masala", "chaat", "Indian"], "authentic blend of spices for chaat and fruit salads"),
    ("Everest Garam Masala",    "Grocery", "Spices",         "Everest", 89,   ["spice", "garam masala", "Indian", "cooking"], "whole spice blend, rich aroma for all Indian curries"),
    ("Tata Salt",               "Grocery", "Pantry Staples", "Tata",    25,   ["salt", "iodised", "staple", "healthy"], "iodised salt, vacuum evaporated for purity"),
    ("Amul Butter",             "Grocery", "Dairy",          "Amul",    55,   ["butter", "dairy", "amul", "cooking"], "pasteurised butter from fresh cream, India's favourite"),
    ("Aashirvaad Multigrain Atta","Grocery","Grains",        "Aashirvaad",249, ["atta", "flour", "multigrain", "healthy"], "blend of 6 grains with wheat for nutritious rotis"),
    ("Dawat Basmati Rice 5kg",  "Grocery", "Grains",         "Dawat",  349,   ["rice", "basmati", "long grain", "premium"], "extra-long grain basmati rice, aged for superior aroma"),
    ("Nescafe Classic 200g",    "Grocery", "Beverages",      "Nescafe", 499,  ["coffee", "instant", "Nescafe", "beverage"], "100% pure soluble coffee, rich aroma and full taste"),
    ("Brooke Bond Red Label Tea","Grocery","Beverages",      "Brooke Bond",179,["tea", "CTC", "Indian", "beverage"], "strong liquoring CTC tea with refreshing flavour"),
    ("Haldiram's Bhujia 400g",  "Grocery", "Snacks",         "Haldiram's",149, ["snack", "bhujia", "namkeen", "Indian"], "crispy besan noodles with authentic spices"),
    ("Lay's Classic Salted 104g","Grocery","Snacks",         "Lay's",   40,   ["chips", "snack", "potato", "crispy"], "wafer-thin potato chips with just the right amount of salt"),
]

for _name, _cat, _subcat, _brand, _price, _tags, _desc_detail in GROCERY_ITEMS:
    for _pack in ["Small", "Medium", "Large", "Value Pack"]:
        _mul = {"Small": 0.6, "Medium": 1.0, "Large": 1.7, "Value Pack": 2.8}[_pack]
        _full_name = f"{_name} — {_pack}"
        _full_desc = (f"{_name}: {_desc_detail}. {_pack} pack for everyday household needs.")
        _specs = {"Brand": _brand, "Pack Size": _pack}
        PRODUCT_TEMPLATES.append(
            (_full_name, _full_desc, _cat, _subcat, _brand,
             round(_price * _mul, 0), [{}], _tags, _specs)
        )


# ── CLOTHING / WOMEN'S DRESSES ────────────────────────────────────────────────

_dress_info = [
    ("Floral Midi Dress",         "floral print midi with V-neck and flutter sleeves"),
    ("Wrap Midi Dress",           "tie-front wrap design in flowing fabric"),
    ("Bodycon Mini Dress",        "stretch bodycon silhouette for nights out"),
    ("Shift Dress",               "relaxed shift cut, great for office wear"),
    ("Maxi Boho Dress",           "bohemian maxi with tassel hem and empire waist"),
    ("A-Line Sundress",           "light cotton A-line sundress with spaghetti straps"),
    ("Shirt Dress",               "collared shirt dress with button-down front"),
    ("Skater Dress",              "flared skater style with empire waist"),
]
_dress_brands = [("Zara", 2499), ("H&M", 1499), ("ONLY", 1799),
                  ("AND", 1999), ("Forever 21", 1599), ("Mango", 2999)]

for _style, _detail in _dress_info:
    for _brand, _price in _dress_brands:
        for _size in ["XS", "S", "M", "L", "XL", "XXL"]:
            for _color in ["Black", "White", "Blue", "Red", "Pink", "Green", "Yellow"]:
                _name = f"{_brand} Women's {_style} {_color} {_size}"
                _desc = (f"{_brand} Women's {_style} in {_color}: {_detail}. "
                         f"Size {_size}, perfect for casual outings and celebrations.")
                _specs = {"Brand": _brand, "Size": _size, "Color": _color, "Gender": "Women"}
                PRODUCT_TEMPLATES.append(
                    (_name, _desc, "Clothing", "Women's Dresses", _brand, _price,
                     [{}], ["dress", "women", "fashion", _brand.lower(), _color.lower()], _specs)
                )

# ── CLOTHING / MEN'S FORMAL SHIRTS ────────────────────────────────────────────

_shirt_brands = [("Van Heusen", 1499), ("Arrow", 1799), ("Peter England", 1299),
                  ("Raymond", 2499), ("Allen Solly", 1599)]
_shirt_styles = [
    ("Slim Fit Check Shirt",   "slim fit with subtle check pattern, ideal for office"),
    ("Regular Fit Plain Shirt","classic plain weave, relaxed regular fit for all occasions"),
    ("Slim Fit Striped Shirt", "sharp vertical stripes, slim cut for a modern office look"),
    ("Casual Linen Shirt",     "breathable linen, relaxed fit for smart casual wear"),
    ("Oxford Collar Shirt",    "Oxford button-down collar, versatile formal to casual"),
    ("Mandarin Collar Shirt",  "band collar design, contemporary ethnic-fusion style"),
]
for _style, _detail in _shirt_styles:
    for _brand, _price in _shirt_brands:
        for _size in ["S", "M", "L", "XL", "XXL", "3XL"]:
            for _color in ["White", "Blue", "Black", "Grey", "Beige", "Navy"]:
                _name = f"{_brand} Men's {_style} {_color} {_size}"
                _desc = (f"{_brand} Men's {_style} in {_color}: {_detail}. "
                         f"Size {_size}, machine washable cotton blend.")
                _specs = {"Brand": _brand, "Size": _size, "Color": _color, "Gender": "Men"}
                PRODUCT_TEMPLATES.append(
                    (_name, _desc, "Clothing", "Men's Formal Shirts", _brand, _price,
                     [{}], ["shirt", "formal", "office", "men", _brand.lower()], _specs)
                )

# ── CLOTHING / WOMEN'S TOPS ────────────────────────────────────────────────────

_top_brands = [("H&M", 699), ("Zara", 1299), ("Forever 21", 899),
                ("Vero Moda", 999), ("Max Fashion", 599)]
_top_styles = [
    ("Crop Top",          "trendy cropped length, casual streetwear style"),
    ("Peplum Top",        "flared peplum hem, flattering silhouette"),
    ("Off-Shoulder Top",  "off-shoulder neckline, romantic and elegant"),
    ("Halter Neck Top",   "halter neck design, ideal for summer outings"),
    ("Oversized T-Shirt", "oversized relaxed fit, comfortable loungewear"),
]
for _style, _detail in _top_styles:
    for _brand, _price in _top_brands:
        for _size in ["XS", "S", "M", "L", "XL"]:
            for _color in ["Black", "White", "Pink", "Blue", "Yellow", "Red", "Green"]:
                _name = f"{_brand} Women's {_style} {_color} {_size}"
                _desc = (f"{_brand} Women's {_style} in {_color}: {_detail}. "
                         f"Size {_size}, lightweight and easy-care fabric.")
                _specs = {"Brand": _brand, "Size": _size, "Color": _color}
                PRODUCT_TEMPLATES.append(
                    (_name, _desc, "Clothing", "Women's Tops", _brand, _price,
                     [{}], ["top", "women", "casual", _brand.lower(), _color.lower()], _specs)
                )

# ── CLOTHING / FOOTWEAR (EXPANDED) ────────────────────────────────────────────

_shoe_brands_m = [
    ("Nike", [("Air Force 1", "classic white leather sneaker, iconic street style", 7995),
               ("React Infinity Run", "maximum cushion running shoe, injury prevention", 12995),
               ("Pegasus 40", "versatile daily trainer, Zoom Air cushioning", 9995)]),
    ("Adidas", [("Stan Smith", "clean leather sneaker, minimal design, timeless", 6999),
                 ("NMD R1", "Boost cushioning, sock-like Primeknit upper", 11995),
                 ("Response Run", "lightweight running, responsive cushioning", 5999)]),
    ("Puma", [("Suede Classic XXI", "suede upper sneaker, streetwear legend since 1968", 4999),
               ("Softride Premier", "maximum softness for walking and daily use", 3999)]),
    ("Skechers", [("Go Walk Max", "Max Cushioning, slip-on comfort for all-day wear", 4499),
                   ("D'Lites", "retro chunky platform sneaker, lightweight sole", 3999)]),
    ("New Balance", [("Fresh Foam 880v13", "plush daily running shoe, stable ride", 11995),
                      ("327", "vintage style sneaker, N logo, heritage look", 6995)]),
    ("ASICS", [("Gel-Kayano 30", "stability running shoe, GEL cushioning front and rear", 12995),
                ("GT-2000 12", "supportive daily trainer for overpronators", 9995)]),
]
for _brand, _models in _shoe_brands_m:
    for _model, _desc_detail, _price in _models:
        for _size in ["UK 6", "UK 7", "UK 8", "UK 9", "UK 10", "UK 11"]:
            for _color in ["Black", "White", "Grey", "Blue", "Red"]:
                _name = f"{_brand} {_model} {_color} {_size}"
                _desc = (f"The {_brand} {_model} in {_color}: {_desc_detail}. "
                         f"Men's size {_size}. Premium comfort and durability.")
                _specs = {"Brand": _brand, "Size": _size, "Color": _color, "Gender": "Men"}
                PRODUCT_TEMPLATES.append(
                    (_name, _desc, "Clothing", "Men's Footwear", _brand, _price,
                     [{}], ["shoes", "men", _brand.lower(), "footwear", _color.lower()], _specs)
                )

# ── ELECTRONICS / BLUETOOTH SPEAKERS ─────────────────────────────────────────

_speaker_items = [
    ("Sony SRS-XB33",   "Sony", 9990,  "Extra Bass waterproof portable speaker, 24hr battery, IP67"),
    ("Sony SRS-XE300",  "Sony", 12990, "Omnidirectional party speaker, X-Balanced driver, IPX4"),
    ("JBL Charge 5",    "JBL",  13990, "Waterproof portable speaker with power bank function, 20hr"),
    ("JBL Flip 6",      "JBL",  9999,  "Compact IP67 waterproof, dual passive radiators, 12hr"),
    ("JBL Xtreme 3",    "JBL",  19999, "Powerful portable with dual tweeters, IP67, 15hr battery"),
    ("Bose SoundLink Flex", "Bose", 14999, "Waterproof wireless, clear stereo sound outdoors or indoors"),
    ("Marshall Emberton II", "Marshall", 12999, "Rock-solid design, 30hr playtime, multi-directional sound"),
    ("Boat Stone 1400", "Boat", 3499,  "14W TWS stereo speaker, IPX7, built-in mic, bass-heavy"),
    ("Mi Outdoor Speaker", "Mi", 1999, "16W, IPX6, 20hr battery, dual passive radiators"),
    ("Amazon Echo Dot 5th Gen", "Amazon", 4999, "Alexa smart speaker with improved bass, smart home hub"),
    ("Google Nest Mini 2nd Gen", "Google", 4499, "Google Assistant, crystal-clear audio, compact design"),
    ("Harman Kardon Onyx Studio 8", "Harman Kardon", 26990, "Premium 50W wireless speaker, 8hr battery, elegant design"),
]
for _name, _brand, _price, _desc_detail in _speaker_items:
    for _color in ["Black", "Blue", "Red", "White"]:
        _full_name = f"{_name} {_color}"
        _desc = f"{_full_name}: {_desc_detail}. Portable Bluetooth speaker in {_color}."
        _specs = {"Brand": _brand, "Color": _color, "Bluetooth": "5.0"}
        PRODUCT_TEMPLATES.append(
            (_full_name, _desc, "Electronics", "Bluetooth Speakers", _brand, _price,
             [{}], ["speaker", "bluetooth", "portable", _brand.lower(), "wireless"], _specs)
        )

# ── HOME & KITCHEN / REFRIGERATOR ─────────────────────────────────────────────

for _brand, _base_price in [
    ("LG", 28990), ("Samsung", 27990), ("Whirlpool", 22990),
    ("Haier", 18990), ("Godrej", 16990),
]:
    for _cap, _mul in [
        ("190L", 0.70), ("260L", 0.85), ("340L", 1.0),
        ("415L", 1.25), ("500L", 1.55), ("600L", 1.90),
    ]:
        for _type in ["Single Door", "Double Door", "Side-by-Side"]:
            _mul2 = {"Single Door": 0.75, "Double Door": 1.0, "Side-by-Side": 1.65}[_type]
            _name = f"{_brand} {_cap} {_type} Refrigerator"
            _desc = (f"The {_brand} {_cap} {_type} Refrigerator features inverter compressor, "
                     f"energy-efficient 5-star rating, and advanced cooling technology.")
            _specs = {"Capacity": _cap, "Type": _type, "Energy": "5 Star", "Inverter": "Yes"}
            PRODUCT_TEMPLATES.append(
                (_name, _desc, "Home & Kitchen", "Refrigerator", _brand,
                 round(_base_price * _mul * _mul2, -2),
                 [{}], ["refrigerator", "fridge", _brand.lower(), "home appliance", "kitchen"], _specs)
            )

# ── HOME & KITCHEN / COOKWARE ─────────────────────────────────────────────────

_cookware = [
    ("Prestige", "Hard Anodised Kadai", "Hard Anodised", "Kadai", 1299),
    ("Hawkins", "Hard Anodised Pressure Pan", "Hard Anodised", "Pressure Pan", 1799),
    ("Meyer", "Non-Stick Frying Pan", "Non-Stick", "Frying Pan", 1499),
    ("Pigeon", "Non-Stick Tawa", "Non-Stick", "Tawa", 799),
    ("Vinod", "Stainless Steel Casserole", "Stainless Steel", "Casserole", 1299),
    ("TTK", "Cast Iron Skillet", "Cast Iron", "Skillet", 1999),
]
for _brand, _full_name, _material, _type, _price in _cookware:
    for _size in ["18cm", "22cm", "24cm", "26cm", "28cm"]:
        _name = f"{_brand} {_full_name} {_size}"
        _desc = (f"{_brand} {_material} {_type} {_size}. Induction-compatible, ergonomic handle, "
                 f"even heat distribution for perfect cooking results.")
        _specs = {"Material": _material, "Size": _size, "Induction": "Compatible"}
        PRODUCT_TEMPLATES.append(
            (_name, _desc, "Home & Kitchen", "Cookware", _brand, _price,
             [{}], ["cookware", _type.lower(), _material.lower(), _brand.lower(), "kitchen"], _specs)
        )

# ── FURNITURE ─────────────────────────────────────────────────────────────────

_furniture = [
    ("Nilkamal Office Chair", "Nilkamal", "Furniture", "Office Chair",
     "Ergonomic office chair with adjustable height, lumbar support, mesh back.", 4999,
     ["chair", "office", "ergonomic", "work from home", "adjustable"]),
    ("Godrej Interio Study Table", "Godrej", "Furniture", "Study Table",
     "Space-efficient study table with storage shelf, engineered wood, modern design.", 5999,
     ["table", "study", "student", "wood", "storage"]),
    ("Urban Ladder Wakefit Mattress", "Wakefit", "Furniture", "Mattress",
     "Orthopaedic memory foam mattress, 6-inch medium-firm, 100-night free trial.", 11999,
     ["mattress", "memory foam", "orthopaedic", "sleep", "comfort"]),
    ("Pepperfry Wooden Bookshelf 5-Tier", "Pepperfry", "Furniture", "Bookshelf",
     "5-tier open bookshelf in sheesham wood, ideal for living room and study.", 6999,
     ["bookshelf", "wood", "storage", "living room", "decor"]),
    ("IKEA KALLAX Shelf Unit", "IKEA", "Furniture", "Storage Shelf",
     "Versatile shelf unit that can be used as a room divider, bookcase, or TV unit.", 7999,
     ["shelf", "storage", "room divider", "IKEA", "modular"]),
    ("Amazon Basics Folding Table", "Amazon Basics", "Furniture", "Folding Table",
     "Lightweight folding table, easy setup, suitable for indoor and outdoor use.", 2999,
     ["folding", "portable", "table", "outdoor", "lightweight"]),
    ("Durian Recliner Sofa", "Durian", "Furniture", "Sofa",
     "3-seater recliner sofa in premium leatherette, wall-hugger design, USB charging.", 29999,
     ["sofa", "recliner", "living room", "leather", "premium"]),
    ("Wooden Street Platform Bed", "Wooden Street", "Furniture", "Bed Frame",
     "Queen-size sheesham wood platform bed, sturdy mortise-and-tenon joints.", 15999,
     ["bed", "wood", "queen", "platform", "bedroom"]),
]
for _name, _brand, _cat, _subcat, _desc, _price, _tags in _furniture:
    for _color in ["Walnut Brown", "Natural Wood", "White", "Dark Oak"]:
        _full_name = f"{_name} — {_color}"
        _full_desc = f"{_desc} Available in {_color} finish."
        _specs = {"Color": _color, "Brand": _brand, "Material": "Engineered Wood"}
        PRODUCT_TEMPLATES.append(
            (_full_name, _full_desc, _cat, _subcat, _brand, _price,
             [{}], _tags + [_color.lower()], _specs)
        )

# ── TOYS & GAMES ──────────────────────────────────────────────────────────────

_toys = [
    ("LEGO Classic Brick Box",           "LEGO",    "Toys & Games", "Building Blocks",  2499,
     ["LEGO", "building", "creative", "kids", "bricks"]),
    ("Funskool Fundoo Shapes Puzzle",    "Funskool", "Toys & Games", "Puzzles",           499,
     ["puzzle", "educational", "toddler", "shapes", "learning"]),
    ("Hot Wheels Basic Car Assortment",  "Hot Wheels","Toys & Games","Die-cast Cars",      149,
     ["cars", "die-cast", "boys", "toy", "Hot Wheels"]),
    ("Barbie Fashionista Doll",          "Barbie",   "Toys & Games", "Dolls",             799,
     ["doll", "Barbie", "fashion", "girls", "toy"]),
    ("Nerf Rival Nemesis MXVII",         "Nerf",     "Toys & Games", "Outdoor Play",      3999,
     ["Nerf", "outdoor", "active play", "boys", "blaster"]),
    ("Skillmatics Brain Games Kit",      "Skillmatics","Toys & Games","Educational",      1299,
     ["educational", "brain games", "kids", "learning", "STEM"]),
    ("Rubik's Cube 3x3",                 "Rubik's",  "Toys & Games", "Puzzles",           499,
     ["puzzle", "cube", "brain teaser", "classic", "Rubik's"]),
    ("Play-Doh Classic Color Pack",      "Play-Doh", "Toys & Games", "Creative Play",     599,
     ["Play-Doh", "creative", "clay", "toddler", "art"]),
    ("Monopoly Classic Board Game",      "Hasbro",   "Toys & Games", "Board Games",      1299,
     ["board game", "Monopoly", "family", "classic", "strategy"]),
    ("Carrom Board Tournament Size",     "Precise",  "Toys & Games", "Board Games",      2499,
     ["carrom", "family", "indoor", "board game", "India"]),
    ("Uno Card Game",                    "Mattel",   "Toys & Games", "Card Games",        299,
     ["Uno", "card game", "family", "party", "quick"]),
    ("Remote Control Car with Light",    "Buddyz",   "Toys & Games", "RC Toys",           999,
     ["RC car", "remote control", "boys", "outdoor", "racing"]),
]
for _name, _brand, _cat, _subcat, _price, _tags in _toys:
    for _age in ["3-5 Years", "5-8 Years", "8-12 Years", "12+ Years"]:
        _full_name = f"{_name} ({_age})"
        _desc = f"{_name} — suitable for children aged {_age}. Safe, non-toxic materials. Educational and fun."
        _specs = {"Age Group": _age, "Brand": _brand}
        PRODUCT_TEMPLATES.append(
            (_full_name, _desc, _cat, _subcat, _brand, _price,
             [{}], _tags + [_age.replace(" ", "-").lower()], _specs)
        )

# ── SPORTS & FITNESS / CRICKET & OUTDOOR ──────────────────────────────────────

_outdoor_sports = [
    ("SG Savage Xtreme Cricket Bat",  "SG",     "Sports & Fitness", "Cricket",    3999,
     "English willow cricket bat, power blade, suitable for turf and leather ball.",
     ["cricket", "bat", "SG", "leather ball", "English willow"]),
    ("Kookaburra Pace Cricket Bat",   "Kookaburra","Sports & Fitness","Cricket",   4999,
     "Grade 2 English willow, traditional shape, premium grip included.",
     ["cricket", "bat", "Kookaburra", "professional", "willow"]),
    ("MRF Chase Master Cricket Bat",  "MRF",    "Sports & Fitness", "Cricket",    2999,
     "Kashmir willow bat endorsed by Virat Kohli, ideal for net practice.",
     ["cricket", "bat", "MRF", "Virat Kohli", "Kashmir willow"]),
    ("Yonex Mavis 600 Shuttlecock",   "Yonex",  "Sports & Fitness", "Badminton",  799,
     "Nylon shuttlecock, feather-like feel, suitable for medium-speed play.",
     ["badminton", "shuttlecock", "Yonex", "nylon", "sport"]),
    ("Li-Ning Air Force 77 Racket",   "Li-Ning","Sports & Fitness", "Badminton",  3499,
     "Lightweight carbon fibre racket, good for attack and defense.",
     ["badminton", "racket", "Li-Ning", "carbon", "lightweight"]),
    ("Wilson US Open Tennis Ball 4-Pack","Wilson","Sports & Fitness","Tennis",     399,
     "ITF approved tennis balls, consistent bounce, extra-duty felt.",
     ["tennis", "ball", "Wilson", "ITF approved", "sport"]),
    ("Nivia Hurricane Football Size 5","Nivia",  "Sports & Fitness", "Football",   999,
     "PVC outer panel, EVA inner bladder, suitable for practice and matches.",
     ["football", "soccer", "size 5", "Nivia", "outdoor"]),
    ("Cosco Sprint Basketball Size 7", "Cosco", "Sports & Fitness", "Basketball", 1299,
     "Rubber construction, suitable for outdoor concrete courts.",
     ["basketball", "size 7", "Cosco", "outdoor", "sport"]),
]
for _name, _brand, _cat, _subcat, _price, _desc, _tags in _outdoor_sports:
    for _variant in ["Standard", "Junior", "Pro Edition", "Club Pack"]:
        _full_name = f"{_name} — {_variant}"
        _full_desc = f"{_desc} {_variant} version for all skill levels."
        _specs = {"Brand": _brand, "Variant": _variant}
        PRODUCT_TEMPLATES.append(
            (_full_name, _full_desc, _cat, _subcat, _brand, _price,
             [{}], _tags + [_variant.lower()], _specs)
        )

# ── AUTOMOTIVE ACCESSORIES ────────────────────────────────────────────────────

_auto_items = [
    ("Bosch S4 Car Battery 45Ah",   "Bosch",    "Automotive", "Car Battery",      4999,
     "Maintenance-free calcium battery, 45Ah capacity, suitable for small sedans.",
     ["car battery", "Bosch", "maintenance-free", "automotive", "power"]),
    ("Michelin Pilot Sport 4 195/65R15","Michelin","Automotive","Tyres",          5999,
     "Premium passenger car tyre, excellent wet and dry grip, long tread life.",
     ["tyre", "Michelin", "premium", "passenger car", "grip"]),
    ("3M Car Polish and Wax 300ml",  "3M",       "Automotive", "Car Care",        799,
     "One-step polish and wax, removes light scratches, restores glossy shine.",
     ["car polish", "wax", "3M", "shine", "car care"]),
    ("Ambrane 20000mAh Car Jump Starter","Ambrane","Automotive","Jump Starter",   2499,
     "12V car jump starter and power bank, LED flashlight, safe for all 12V vehicles.",
     ["jump starter", "emergency", "power bank", "Ambrane", "safety"]),
    ("Philips H4 Headlight Bulb 60/55W","Philips","Automotive","Lighting",        599,
     "Standard headlight bulb, 30% more light than regular bulbs, DOT approved.",
     ["headlight", "H4", "Philips", "bulb", "automotive lighting"]),
    ("Viofo A129 Plus Dash Cam",     "Viofo",    "Automotive", "Dash Camera",     7999,
     "Full HD 1080P front and rear dash camera, GPS, night vision, loop recording.",
     ["dash cam", "dashcam", "GPS", "safety", "recording"]),
]
for _name, _brand, _cat, _subcat, _price, _desc, _tags in _auto_items:
    for _model in ["Standard", "Premium", "Value Pack", "Professional"]:
        _full_name = f"{_name} — {_model}"
        _full_desc = f"{_desc} ({_model} variant.)"
        _specs = {"Brand": _brand, "Variant": _model}
        PRODUCT_TEMPLATES.append(
            (_full_name, _full_desc, _cat, _subcat, _brand, _price,
             [{}], _tags + [_model.lower()], _specs)
        )

# ── PET SUPPLIES ──────────────────────────────────────────────────────────────

_pet_items = [
    ("Pedigree Adult Dog Food Chicken & Vegetables 3kg","Pedigree","Pet Supplies","Dog Food",  799,
     "Complete nutrition for adult dogs, real chicken and vegetables, DHA for brain health.",
     ["dog food", "Pedigree", "adult dog", "chicken", "nutrition"]),
    ("Royal Canin Cat Adult Dry Food 2kg","Royal Canin","Pet Supplies","Cat Food",   1499,
     "Precisely balanced nutrition for adult cats, supports digestive health and coat.",
     ["cat food", "Royal Canin", "adult cat", "dry food", "premium"]),
    ("Heads Up For Tails Dog Collar",  "Heads Up For Tails","Pet Supplies","Pet Accessories", 499,
     "Nylon adjustable dog collar, reflective strip, durable and washable.",
     ["dog collar", "pet", "adjustable", "reflective", "dog"]),
    ("Drools Focus SuperPremium Puppy Dog Food 3kg","Drools","Pet Supplies","Dog Food", 649,
     "High protein puppy food, DHA for brain development, supports strong bones.",
     ["puppy food", "Drools", "puppy", "high protein", "nutrition"]),
]
for _name, _brand, _cat, _subcat, _price, _desc, _tags in _pet_items:
    for _size in ["Small", "Medium", "Large", "Extra Large"]:
        _full_name = f"{_name} — {_size}"
        _full_desc = f"{_desc} Available in {_size} size."
        _specs = {"Brand": _brand, "Size": _size}
        PRODUCT_TEMPLATES.append(
            (_full_name, _full_desc, _cat, _subcat, _brand, _price,
             [{}], _tags + [_size.lower()], _specs)
        )

# ── BABY PRODUCTS ─────────────────────────────────────────────────────────────

_baby_items = [
    ("Pampers Premium Care Newborn Diapers 72 Count",  "Pampers",   "Baby Products", "Diapers",       899,
     "Ultra-soft diapers with Aloe Vera lotion, 12-hour protection, wetness indicator.",
     ["diaper", "Pampers", "newborn", "baby", "soft"]),
    ("Himalaya Gentle Baby Wash 400ml",                "Himalaya",  "Baby Products", "Baby Care",     249,
     "Tear-free gentle baby wash, natural extracts, safe for sensitive newborn skin.",
     ["baby wash", "Himalaya", "gentle", "natural", "sensitive skin"]),
    ("Chicco Ohlalà Baby Stroller",                    "Chicco",    "Baby Products", "Stroller",     7999,
     "Lightweight single stroller with reclining seat, adjustable handlebar, easy fold.",
     ["stroller", "Chicco", "baby", "lightweight", "foldable"]),
    ("Fisher-Price Kick and Play Piano Gym",            "Fisher-Price","Baby Products","Baby Toys",    1999,
     "5-in-1 musical activity gym grows with baby, detachable piano, tummy time mat.",
     ["baby gym", "Fisher-Price", "musical", "developmental", "tummy time"]),
    ("Mee Mee Anti-Colic Feeding Bottle 250ml",        "Mee Mee",   "Baby Products", "Feeding",       299,
     "Anti-colic feeding bottle, BPA-free, slow-flow teat ideal for newborns.",
     ["feeding bottle", "anti-colic", "BPA-free", "newborn", "baby"]),
]
for _name, _brand, _cat, _subcat, _price, _desc, _tags in _baby_items:
    for _variant in ["0-3 Months", "3-6 Months", "6-12 Months", "12-18 Months"]:
        _full_name = f"{_name} ({_variant})"
        _full_desc = f"{_desc} Suitable for babies aged {_variant}."
        _specs = {"Brand": _brand, "Age": _variant}
        PRODUCT_TEMPLATES.append(
            (_full_name, _full_desc, _cat, _subcat, _brand, _price,
             [{}], _tags + [_variant.replace(" ", "-").lower()], _specs)
        )

# ── OFFICE SUPPLIES & STATIONERY ──────────────────────────────────────────────

_office_items = [
    ("Classmate Premium Notebook A4 200 Pages", "Classmate",  "Stationery", "Notebooks",  199,
     "200-page premium ruled notebook, hard cover, micro perforated pages.",
     ["notebook", "ruled", "hard cover", "student", "writing"]),
    ("Pilot V7 Hi-Tecpoint Pen Blue",            "Pilot",      "Stationery", "Pens",        99,
     "Liquid ink rollerball pen, 0.7mm tip, smooth and consistent writing.",
     ["pen", "rollerball", "liquid ink", "Pilot", "writing"]),
    ("Cello PinPoint Ball Pen 10-Pack",          "Cello",      "Stationery", "Pens",        50,
     "Smooth writing ballpoint pen, 10-pack in blue, reliable everyday pen.",
     ["pen", "ballpoint", "office", "budget", "pack"]),
    ("Faber-Castell Colour Pencils 24-Pack",     "Faber-Castell","Stationery","Art Supplies",299,
     "24 vibrant colours, break-resistant lead, suitable for school and hobby artists.",
     ["colour pencils", "art", "Faber-Castell", "school", "kids"]),
    ("3M Post-it Notes 100 Sheets Assorted",     "3M",         "Stationery", "Office Essentials",299,
     "Self-adhesive notes in assorted colours, easy peel and stick, 100 sheets.",
     ["post-it", "sticky notes", "3M", "office", "organisation"]),
    ("Kokuyo Campus Notebook B5 Dotted",         "Kokuyo",     "Stationery", "Notebooks",  199,
     "Dotted grid B5 notebook, ultra-thin paper, no bleed, ideal for bujo.",
     ["notebook", "dotted", "bullet journal", "Kokuyo", "thin"]),
]
for _name, _brand, _cat, _subcat, _price, _desc, _tags in _office_items:
    for _pack in ["Single", "Pack of 2", "Pack of 5", "Pack of 10"]:
        _mul = {"Single": 1.0, "Pack of 2": 1.8, "Pack of 5": 4.0, "Pack of 10": 7.5}[_pack]
        _full_name = f"{_name} — {_pack}"
        _full_desc = f"{_desc} ({_pack} — great value.)"
        _specs = {"Brand": _brand, "Pack": _pack}
        PRODUCT_TEMPLATES.append(
            (_full_name, _full_desc, _cat, _subcat, _brand,
             round(_price * _mul, 0),
             [{}], _tags + [_pack.lower()], _specs)
        )

# ── ELECTRONICS / GAMING PERIPHERALS ─────────────────────────────────────────

_gaming = [
    ("Logitech G213 Prodigy Gaming Keyboard", "Logitech", 4495,
     "Membrane gaming keyboard with RGB lighting, spill-resistant, 5 programmable keys.",
     ["keyboard", "gaming", "RGB", "Logitech", "membrane"]),
    ("Razer DeathAdder Essential Gaming Mouse", "Razer", 2695,
     "6400 DPI optical sensor, 5 Hyperesponse buttons, ergonomic right-hand design.",
     ["mouse", "gaming", "Razer", "ergonomic", "optical"]),
    ("Logitech G502 HERO Gaming Mouse", "Logitech", 3995,
     "25K DPI HERO sensor, adjustable weights, 11 programmable buttons.",
     ["mouse", "gaming", "Logitech", "DPI", "weights"]),
    ("Corsair K70 RGB Pro Mechanical Keyboard", "Corsair", 12995,
     "Cherry MX Red switches, per-key RGB, aircraft-grade aluminium frame.",
     ["keyboard", "mechanical", "Cherry MX", "RGB", "Corsair"]),
    ("SteelSeries Arctis 7 Wireless Headset", "SteelSeries", 14999,
     "Lossless 2.4GHz wireless gaming headset, 24hr battery, ClearCast mic.",
     ["gaming headset", "wireless", "SteelSeries", "surround sound", "mic"]),
    ("Logitech G29 Driving Force Racing Wheel", "Logitech", 29995,
     "Force feedback racing wheel for PS5/PS4/PC, stainless steel paddle shifters.",
     ["racing wheel", "PS5", "gaming", "Logitech", "force feedback"]),
]
for _name, _brand, _price, _desc, _tags in _gaming:
    for _color in ["Black", "White"]:
        _full_name = f"{_name} — {_color}"
        _full_desc = f"{_desc} Available in {_color}."
        _specs = {"Brand": _brand, "Color": _color}
        PRODUCT_TEMPLATES.append(
            (_full_name, _full_desc, "Electronics", "Gaming Peripherals", _brand, _price,
             [{}], _tags + [_color.lower()], _specs)
        )

# ── ELECTRONICS / SMART HOME ──────────────────────────────────────────────────

_smarthome = [
    ("Amazon Echo 4th Gen",          "Amazon", 5999,  "Alexa voice control, powerful sound, smart home hub with Zigbee.",           ["Alexa", "smart home", "voice control", "hub", "WiFi"]),
    ("Google Nest Hub 2nd Gen",      "Google", 7999,  "7-inch smart display with Google Assistant, sleep sensing, camera-free.",    ["Google", "smart display", "Nest", "voice control", "smart home"]),
    ("Philips Hue Smart Bulb E27 9W","Philips", 2499, "16 million colours, voice/app control, works with Alexa & Google.",          ["smart bulb", "Philips Hue", "RGB", "Alexa", "Google"]),
    ("TP-Link Tapo Smart Plug C200", "TP-Link",  999, "Smart Wi-Fi plug with energy monitoring, voice control, remote scheduling.", ["smart plug", "TP-Link", "energy monitor", "Alexa", "Google"]),
    ("Mi Smart Band 8",              "Mi",      3999,  "1.62-inch AMOLED, 16-day battery, 150+ sports modes, sleep tracking.",       ["fitness band", "Mi Band", "AMOLED", "sleep", "health"]),
    ("Arlo Essential Spotlight Camera","Arlo",  9999, "Wire-free 1080P security camera with colour night vision and spotlight.",    ["security camera", "wireless", "Arlo", "night vision", "outdoor"]),
    ("Nest Protect Smoke Alarm",     "Google", 10999, "Smart smoke and CO alarm, speaks to tell you what's wrong and where.",      ["smoke alarm", "carbon monoxide", "Google Nest", "safety", "smart"]),
]
for _name, _brand, _price, _desc, _tags in _smarthome:
    for _variant in ["Single", "Starter Pack", "Twin Pack"]:
        _mul = {"Single": 1.0, "Starter Pack": 1.75, "Twin Pack": 1.85}[_variant]
        _full_name = f"{_name} — {_variant}"
        _full_desc = f"{_desc} ({_variant}.)"
        _specs = {"Brand": _brand, "Pack": _variant}
        PRODUCT_TEMPLATES.append(
            (_full_name, _full_desc, "Electronics", "Smart Home", _brand,
             round(_price * _mul, -2),
             [{}], _tags + [_variant.lower()], _specs)
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  INDIAN DEMOGRAPHIC DATA
# ═══════════════════════════════════════════════════════════════════════════════

FIRST_NAMES_M = ["Rahul", "Amit", "Vijay", "Arjun", "Rohan", "Sanjay", "Vikram",
                  "Karthik", "Pradeep", "Ankit", "Suresh", "Rajesh", "Naveen",
                  "Deepak", "Arun", "Vishal", "Abhishek", "Nitin", "Prakash",
                  "Varun", "Hardik", "Mohit", "Gaurav", "Piyush", "Tushar"]
FIRST_NAMES_F = ["Priya", "Sneha", "Deepa", "Kavya", "Anita", "Meera", "Rekha",
                  "Pooja", "Divya", "Shalini", "Swati", "Lakshmi", "Rashmi",
                  "Nisha", "Seema", "Geeta", "Sunita", "Neha", "Komal", "Anjali",
                  "Ritika", "Shreya", "Mansi", "Tanvi", "Ishita"]
LAST_NAMES    = ["Sharma", "Patel", "Kumar", "Reddy", "Nair", "Menon", "Singh",
                  "Iyer", "Gupta", "Desai", "Rao", "Krishnan", "Shah", "Pillai",
                  "Nambiar", "Joshi", "Tiwari", "Bhat", "Agarwal", "Chopra",
                  "Mishra", "Saxena", "Verma", "Malhotra", "Narayanan"]
CITIES_STATES = [
    ("Mumbai", "Maharashtra", "400001"), ("Delhi", "Delhi", "110001"),
    ("Bangalore", "Karnataka", "560001"), ("Chennai", "Tamil Nadu", "600001"),
    ("Hyderabad", "Telangana", "500001"), ("Pune", "Maharashtra", "411001"),
    ("Kolkata", "West Bengal", "700001"), ("Ahmedabad", "Gujarat", "380001"),
    ("Jaipur", "Rajasthan", "302001"), ("Surat", "Gujarat", "395001"),
    ("Lucknow", "Uttar Pradesh", "226001"), ("Kanpur", "Uttar Pradesh", "208001"),
    ("Nagpur", "Maharashtra", "440001"), ("Indore", "Madhya Pradesh", "452001"),
    ("Thane", "Maharashtra", "400601"), ("Bhopal", "Madhya Pradesh", "462001"),
    ("Visakhapatnam", "Andhra Pradesh", "530001"), ("Coimbatore", "Tamil Nadu", "641001"),
    ("Kochi", "Kerala", "682001"), ("Chandigarh", "Punjab", "160001"),
]
SEGMENTS = ["budget"] * 40 + ["mid-range"] * 40 + ["premium"] * 20

SEARCH_QUERIES = [
    "wireless headphones with noise cancellation",
    "best laptop under 50000",
    "running shoes for men",
    "pressure cooker 5 litre",
    "whey protein chocolate flavour",
    "iPhone 15 latest model",
    "Samsung TV 55 inch 4K",
    "yoga mat non slip thick",
    "face wash for oily skin",
    "lightweight laptop for college",
    "air fryer low oil cooking",
    "protein powder for weight loss",
    "smartwatch with health tracking",
    "women ethnic kurta cotton",
    "gaming laptop RTX graphics",
    "water purifier RO UV",
    "mixer grinder 750 watt",
    "budget smartphone 5G under 20000",
    "skincare routine dry skin",
    "dumbbells home gym set",
    "bestselling books 2024",
    "cooking oil heart healthy",
    "anti-dandruff shampoo",
    "Amazon Echo smart speaker",
    "tablet for kids education",
    "mens formal shirt office wear",
    "baby toys 1 year old",
    "sunscreen SPF 50 no white cast",
    "bluetooth speaker waterproof outdoor",
    "mechanical keyboard gaming",
]

ORDER_STATUS_DIST  = ["placed"] * 5 + ["confirmed"] * 10 + ["shipped"] * 15 + \
                     ["delivered"] * 50 + ["cancelled"] * 12 + ["returned"] * 8
PAYMENT_STATUS_MAP = {
    "placed":    ["paid", "pending"],
    "confirmed": ["paid", "paid", "paid", "pending"],
    "shipped":   ["paid"],
    "delivered": ["paid"],
    "cancelled": ["refunded", "failed", "pending"],
    "returned":  ["refunded"],
}
SHIPMENT_STATUS_MAP = {
    "placed":    "processing",
    "confirmed": "dispatched",
    "shipped":   "in_transit",
    "delivered": "delivered",
    "cancelled": "failed",
    "returned":  "delivered",
}
CANCEL_REASONS = [
    "Changed my mind", "Found a better price elsewhere", "Ordered by mistake",
    "Product not needed anymore", "Delivery was taking too long",
    "Quality not as expected after review", "Price dropped after ordering",
]


# ═══════════════════════════════════════════════════════════════════════════════
#  GENERATORS
# ═══════════════════════════════════════════════════════════════════════════════

def new_id():
    return str(uuid.uuid4())


def rand_dt(days_back=730):
    return datetime.utcnow() - timedelta(
        days=random.randint(0, days_back),
        hours=random.randint(0, 23),
        minutes=random.randint(0, 59),
    )


def generate_products():
    """Return list of product dicts, one per template × variant."""
    rows = []
    for name_tpl, desc, cat, subcat, brand, base_price, variants, tags, specs in PRODUCT_TEMPLATES:
        for var in variants:
            var_suffix = " ".join(v for v in var.values() if v)
            _name = f"{name_tpl} {var_suffix}".strip()
            _specs = {**specs, **var}
            rows.append({
                "id": new_id(),
                "name": _name[:250],
                "description": desc,
                "category": cat,
                "subcategory": subcat,
                "brand": brand,
                "price": float(base_price),
                "discount_pct": float(random.choice([0, 0, 5, 5, 10, 10, 15, 20, 25, 30])),
                "inventory_count": random.randint(0, 300),
                "rating_avg": 0.0,
                "rating_count": 0,
                "primary_image": f"https://picsum.photos/seed/{abs(hash(_name)) % 9999}/800/600",
                "tags": json.dumps(tags),
                "specifications": json.dumps(_specs),
                "is_active": True,
                "created_at": rand_dt(730),
            })
    # deduplicate by name (keep first occurrence)
    seen, unique = set(), []
    for r in rows:
        if r["name"] not in seen:
            seen.add(r["name"])
            unique.append(r)
    return unique


def generate_customers(n=10000):
    rows, emails = [], set()
    for i in range(n):
        gender = random.choice(["M", "F"])
        first  = random.choice(FIRST_NAMES_M if gender == "M" else FIRST_NAMES_F)
        last   = random.choice(LAST_NAMES)
        # ensure unique email
        base_email = f"{first.lower()}.{last.lower()}{random.randint(1, 9999)}"
        email = f"{base_email}@{'gmail' if random.random() > 0.4 else 'yahoo'}.com"
        while email in emails:
            email = f"{first.lower()}.{last.lower()}{random.randint(1000, 99999)}@gmail.com"
        emails.add(email)
        city, state, pin = random.choice(CITIES_STATES)
        rows.append({
            "user_id":    new_id(),
            "email":      email,
            "first_name": first,
            "last_name":  last,
            "phone":      f"+91{''.join([str(random.randint(0,9)) for _ in range(10)])}",
            "city":       city,
            "state":      state,
            "pincode":    pin,
            "segment":    random.choice(SEGMENTS),
            "created_at": rand_dt(1095),
        })
    return rows


def generate_orders(customers, products, n=50000):
    product_ids   = [p["id"] for p in products]
    product_price = {p["id"]: p["price"] * (1 - p["discount_pct"] / 100) for p in products}
    cust_ids      = [c["user_id"] for c in customers]

    rows = []
    for _ in range(n):
        uid    = random.choice(cust_ids)
        status = random.choice(ORDER_STATUS_DIST)
        pay    = random.choice(PAYMENT_STATUS_MAP[status])
        ship   = SHIPMENT_STATUS_MAP[status]

        # Cart: 1-5 items
        n_items = random.randint(1, 5)
        cart_products = random.sample(product_ids, min(n_items, len(product_ids)))
        cart = []
        total = 0.0
        for pid in cart_products:
            qty   = random.randint(1, 3)
            price = round(product_price.get(pid, 500.0), 2)
            cart.append({"product_id": pid, "quantity": qty, "unit_price": price})
            total += qty * price

        created = rand_dt(730)
        eta = (created + timedelta(days=random.randint(3, 10))).date()

        rows.append({
            "order_id":            new_id(),
            "user_id":             uid,
            "order_status":        status,
            "payment_status":      pay,
            "shipment_status":     ship,
            "total_amount":        round(total, 2),
            "estimated_delivery":  str(eta),
            "cancellation_reason": random.choice(CANCEL_REASONS) if status in ("cancelled", "returned") else None,
            "cart_activity":       json.dumps(cart),
            "created_at":          created,
        })
    return rows


def generate_browsing_events(customers, products, n=150000):
    cust_ids    = [c["user_id"] for c in customers]
    product_ids = [p["id"] for p in products]
    event_types = ["view"] * 60 + ["add_to_cart"] * 20 + ["wishlist"] * 10 + ["purchase"] * 10

    rows = []
    for _ in range(n):
        rows.append({
            "id":         new_id(),
            "user_id":    random.choice(cust_ids),
            "product_id": random.choice(product_ids),
            "event_type": random.choice(event_types),
            "session_id": new_id()[:8],
            "created_at": rand_dt(365),
        })
    return rows


def generate_wishlists(customers, products, n=30000):
    cust_ids    = [c["user_id"] for c in customers]
    product_ids = [p["id"] for p in products]
    seen = set()
    rows = []
    attempts = 0
    while len(rows) < n and attempts < n * 3:
        attempts += 1
        uid = random.choice(cust_ids)
        pid = random.choice(product_ids)
        key = (uid, pid)
        if key not in seen:
            seen.add(key)
            rows.append({
                "id":         new_id(),
                "user_id":    uid,
                "product_id": pid,
                "created_at": rand_dt(365),
            })
    return rows


def generate_search_logs(customers, products, n=15000):
    cust_ids    = [c["user_id"] for c in customers] + [None] * 2000
    product_ids = [p["id"] for p in products] + [None] * 5000
    rows = []
    for _ in range(n):
        rows.append({
            "id":                 new_id(),
            "user_id":            random.choice(cust_ids),
            "query":              random.choice(SEARCH_QUERIES),
            "results_count":      random.randint(0, 80),
            "clicked_product_id": random.choice(product_ids),
            "search_type":        random.choice(["keyword"] * 7 + ["semantic"] * 3),
            "created_at":         rand_dt(365),
        })
    return rows


# ═══════════════════════════════════════════════════════════════════════════════
#  DATABASE LOADERS  (psycopg2 execute_values for bulk speed)
# ═══════════════════════════════════════════════════════════════════════════════

BATCH = 1000  # rows per INSERT


def _bulk(cur, table, cols, rows, extra_cols=""):
    sql = f"INSERT INTO {table} ({','.join(cols)}{extra_cols}) VALUES %s ON CONFLICT DO NOTHING"
    data = [tuple(r[c] for c in cols) for r in rows]
    psycopg2.extras.execute_values(cur, sql, data, page_size=BATCH)


def load_products(db_conn, products):
    cur = db_conn.cursor()
    cols = ["id", "name", "description", "category", "subcategory", "brand",
            "price", "discount_pct", "inventory_count", "rating_avg", "rating_count",
            "primary_image", "tags", "specifications", "is_active", "created_at"]
    _bulk(cur, "products", cols, products)
    db_conn.commit()
    cur.close()


def load_customers(db_conn, customers):
    cur  = db_conn.cursor()
    cols = ["user_id", "email", "first_name", "last_name", "phone",
            "city", "state", "pincode", "segment", "created_at"]
    _bulk(cur, "customers", cols, customers)
    db_conn.commit()
    cur.close()


def load_orders(db_conn, orders):
    cur  = db_conn.cursor()
    cols = ["order_id", "user_id", "order_status", "payment_status", "shipment_status",
            "total_amount", "estimated_delivery", "cancellation_reason",
            "cart_activity", "created_at"]
    _bulk(cur, "orders", cols, orders)
    db_conn.commit()
    cur.close()


def load_browsing_events(db_conn, events):
    cur  = db_conn.cursor()
    cols = ["id", "user_id", "product_id", "event_type", "session_id", "created_at"]
    _bulk(cur, "browsing_events", cols, events)
    db_conn.commit()
    cur.close()


def load_wishlists(db_conn, wishlists):
    cur  = db_conn.cursor()
    cols = ["id", "user_id", "product_id", "created_at"]
    _bulk(cur, "wishlists", cols, wishlists)
    db_conn.commit()
    cur.close()


def load_search_logs(db_conn, logs):
    cur  = db_conn.cursor()
    cols = ["id", "user_id", "query", "results_count",
            "clicked_product_id", "search_type", "created_at"]
    _bulk(cur, "search_logs", cols, logs)
    db_conn.commit()
    cur.close()


# ═══════════════════════════════════════════════════════════════════════════════
#  EMBEDDINGS
# ═══════════════════════════════════════════════════════════════════════════════

def generate_embeddings(db_conn, products, skip=False):
    if skip:
        print("  [--skip-embed] Skipping embeddings.")
        return

    from embeddings import embed_batch, build_product_text
    from pgvector.psycopg2 import register_vector
    register_vector(db_conn)

    cur   = db_conn.cursor()
    EBATCH = 100
    total = len(products)

    print(f"\n  Embedding {total} products (batches of {EBATCH})...")
    for i in range(0, total, EBATCH):
        batch = products[i: i + EBATCH]

        class _P:
            pass

        texts = []
        for p in batch:
            obj = _P()
            obj.name        = p["name"]
            obj.brand       = p["brand"]
            obj.category    = p["category"]
            obj.subcategory = p.get("subcategory", "")
            obj.description = p["description"]
            obj.tags        = json.loads(p["tags"]) if isinstance(p["tags"], str) else p["tags"]
            texts.append(build_product_text(obj))

        try:
            embeddings = embed_batch(texts)
        except Exception as e:
            print(f"  ✗ Batch {i // EBATCH + 1} failed: {e}")
            continue

        for p, emb in zip(batch, embeddings):
            cur.execute(
                "UPDATE products SET embedding = %s WHERE id = %s",
                (emb, p["id"])
            )
        db_conn.commit()
        done = min(i + EBATCH, total)
        print(f"  ✓ {done}/{total} embedded")
        if i + EBATCH < total:
            time.sleep(0.4)

    cur.close()


# ═══════════════════════════════════════════════════════════════════════════════
#  RATINGS — compute from generated review-like data
# ═══════════════════════════════════════════════════════════════════════════════

def assign_ratings(db_conn, products):
    """Assign synthetic avg rating + count to each product (no real reviews table needed)."""
    cur = db_conn.cursor()
    for p in products:
        avg   = round(random.gauss(4.0, 0.7), 1)
        avg   = max(1.0, min(5.0, avg))
        count = random.randint(3, 850)
        cur.execute(
            "UPDATE products SET rating_avg=%s, rating_count=%s WHERE id=%s",
            (avg, count, p["id"])
        )
    db_conn.commit()
    cur.close()


# ═══════════════════════════════════════════════════════════════════════════════
#  CSV EXPORT
# ═══════════════════════════════════════════════════════════════════════════════

def export_csv(name, rows, field_names):
    os.makedirs(EXPORT_DIR, exist_ok=True)
    path = os.path.join(EXPORT_DIR, f"{name}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=field_names, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"  → {path}  ({len(rows):,} rows)")


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset",       action="store_true", help="Drop and recreate all tables")
    parser.add_argument("--skip-embed",  action="store_true", help="Skip Azure OpenAI embedding step")
    parser.add_argument("--csv",         action="store_true", help="Export data to ./data/*.csv")
    args = parser.parse_args()

    db = conn()
    cur = db.cursor()

    if args.reset:
        print("Dropping all tables...")
        cur.execute(DROP_TABLES)
        db.commit()
        print("Recreating product tables (SQLAlchemy)...")
        # Recreate via SQLAlchemy so pgvector Vector type is set up correctly
        from database import engine, Base
        from models import Product, ProductImage, Review, Category
        from pgvector.psycopg2 import register_vector as rv
        rv(db)
        Base.metadata.create_all(bind=engine)

    print("Creating new dataset tables (customers, orders, events…)...")
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
    cur.execute(DDL)
    db.commit()
    cur.close()

    # ── PRODUCTS ──────────────────────────────────────────────────────────────
    print("\n[1/7] Generating products...")
    products = generate_products()
    print(f"      {len(products):,} unique products generated")
    print("      Loading into PostgreSQL...")
    load_products(db, products)
    print("      Assigning ratings...")
    assign_ratings(db, products)

    # ── EMBEDDINGS ────────────────────────────────────────────────────────────
    print("\n[2/7] Generating embeddings (Azure OpenAI text-embedding-3-small)...")
    generate_embeddings(db, products, skip=args.skip_embed)

    # ── CATEGORIES ────────────────────────────────────────────────────────────
    print("\n[3/7] Syncing categories...")
    cur = db.cursor()
    cats = set()
    for p in products:
        cats.add((p["subcategory"], p["category"]))
    for subcat, cat in cats:
        cur.execute(
            "INSERT INTO categories (id, name, parent_name) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (new_id(), subcat, cat)
        )
    db.commit()
    cur.close()
    print(f"      {len(cats)} categories synced")

    # ── CUSTOMERS ─────────────────────────────────────────────────────────────
    print("\n[4/7] Generating 10,000 customers...")
    customers = generate_customers(10000)
    load_customers(db, customers)
    print(f"      {len(customers):,} customers loaded")

    # ── ORDERS ────────────────────────────────────────────────────────────────
    print("\n[5/7] Generating 50,000 orders...")
    orders = generate_orders(customers, products, 50000)
    load_orders(db, orders)
    print(f"      {len(orders):,} orders loaded")

    # ── BROWSING EVENTS ───────────────────────────────────────────────────────
    print("\n[6/7] Generating 150,000 browsing events...")
    events = generate_browsing_events(customers, products, 150000)
    load_browsing_events(db, events)
    print(f"      {len(events):,} events loaded")

    # ── WISHLISTS + SEARCH LOGS ───────────────────────────────────────────────
    print("\n[7/7] Generating wishlists (30k) and search logs (15k)...")
    wishlists = generate_wishlists(customers, products, 30000)
    load_wishlists(db, wishlists)
    search_logs = generate_search_logs(customers, products, 15000)
    load_search_logs(db, search_logs)
    print(f"      {len(wishlists):,} wishlist entries + {len(search_logs):,} search logs loaded")

    # ── CSV EXPORT ────────────────────────────────────────────────────────────
    if args.csv:
        print("\nExporting CSVs to ./data/ ...")
        export_csv("products",  products,  ["id","name","category","subcategory","brand",
                                            "price","discount_pct","inventory_count",
                                            "rating_avg","rating_count","tags","specifications",
                                            "description"])
        export_csv("customers", customers, ["user_id","email","first_name","last_name",
                                            "phone","city","state","pincode","segment","created_at"])
        export_csv("orders",    orders,    ["order_id","user_id","order_status","payment_status",
                                            "shipment_status","total_amount","estimated_delivery",
                                            "cancellation_reason","cart_activity","created_at"])
        export_csv("search_logs", search_logs, ["id","user_id","query","results_count",
                                                "clicked_product_id","search_type","created_at"])

    # ── SUMMARY ───────────────────────────────────────────────────────────────
    cur = db.cursor()
    cur.execute("SELECT COUNT(*) FROM products WHERE is_active=true")
    p_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM products WHERE embedding IS NOT NULL")
    e_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM customers")
    c_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM orders")
    o_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM browsing_events")
    ev_count = cur.fetchone()[0]
    cur.execute("SELECT order_status, COUNT(*) FROM orders GROUP BY order_status ORDER BY COUNT(*) DESC")
    status_dist = cur.fetchall()
    cur.close()
    db.close()

    print(f"""
{'='*60}
  DATASET LOADED SUCCESSFULLY
{'='*60}
  Table               Rows
  ──────────────────  ──────────
  products            {p_count:>10,}   (embedded: {e_count:,})
  customers           {c_count:>10,}
  orders              {o_count:>10,}
  browsing_events     {ev_count:>10,}
  wishlists           {len(wishlists):>10,}
  search_logs         {len(search_logs):>10,}

  Order status distribution:
  {''.join(f"    {s}: {n:,}" + chr(10) for s, n in status_dist)}
  API running at: http://localhost:8001/docs
{'='*60}
""")


if __name__ == "__main__":
    main()
