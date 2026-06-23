#!/usr/bin/env bash
# seed_products.sh — Seed the product catalogue with synthetic data and embeddings
# Run after setup_db.sh and after starting product_catalogue at least once
# (so SQLAlchemy creates the tables).
#
# Usage:  bash scripts/seed_products.sh

set -e
cd "$(dirname "$0")/../src/product_catalogue"

echo "[seed] Installing product_catalogue dependencies..."
pip install -r requirements.txt -q

echo "[seed] Seeding products (5,000 rows)..."
python seed_data.py

echo "[seed] Generating 1536-dim embeddings via Azure OpenAI (may take 2-3 min)..."
python generate_dataset.py

echo "[seed] Done. Products are indexed and ready for semantic search."
