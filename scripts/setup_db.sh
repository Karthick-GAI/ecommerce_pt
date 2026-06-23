#!/usr/bin/env bash
# setup_db.sh — Create the PostgreSQL database and enable pgvector
# Run once before starting any service that uses PostgreSQL.
#
# Prerequisites: PostgreSQL 15+ running locally, psql on PATH.
# Usage:  bash scripts/setup_db.sh

set -e

DB_NAME="${PGDATABASE:-ecommerce}"
DB_USER="${PGUSER:-postgres}"

echo "[setup_db] Creating database '$DB_NAME' if it does not exist..."
psql -U "$DB_USER" -tc "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'" \
  | grep -q 1 || psql -U "$DB_USER" -c "CREATE DATABASE $DB_NAME;"

echo "[setup_db] Enabling pgvector extension..."
psql -U "$DB_USER" -d "$DB_NAME" -c "CREATE EXTENSION IF NOT EXISTS vector;"

echo "[setup_db] Done. Database '$DB_NAME' is ready."
echo ""
echo "Next: copy .env.example → .env, fill in your Azure OpenAI credentials,"
echo "      then run: bash scripts/seed_products.sh"
