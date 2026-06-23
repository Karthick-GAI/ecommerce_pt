#!/usr/bin/env bash
# compose_up.sh — One-command startup for the E-Commerce AI Platform
#
# What this does:
#   1. Stops any standalone postgres containers that would conflict on port 5432
#   2. Ensures the pgdata volume exists (creates it if missing)
#   3. Runs podman-compose up --build
#
# Usage:
#   bash scripts/compose_up.sh          # build + start everything
#   bash scripts/compose_up.sh --no-build  # start without rebuilding images
#   bash scripts/compose_up.sh --down   # stop and remove containers

set -e
cd "$(dirname "$0")/.."

# ── Stop mode ────────────────────────────────────────────────────────────────
if [[ "$1" == "--down" ]]; then
  echo "[compose] Stopping all containers..."
  podman-compose down
  exit 0
fi

BUILD_FLAG="--build"
[[ "$1" == "--no-build" ]] && BUILD_FLAG=""

# ── Pre-flight: check .env ───────────────────────────────────────────────────
if [ ! -f ".env" ]; then
  echo "[compose] ERROR: .env not found. Copy and fill it first:"
  echo "  cp .env.example .env"
  exit 1
fi

# ── Stop standalone postgres containers that occupy port 5432 ────────────────
echo "[compose] Stopping standalone postgres containers (freeing port 5432)..."
for name in podman-postgres kartai-db; do
  if podman ps --format '{{.Names}}' | grep -q "^${name}$"; then
    podman stop "$name" && echo "  stopped: $name"
  fi
done

# ── Ensure pgdata volume exists ──────────────────────────────────────────────
if ! podman volume inspect pgdata &>/dev/null; then
  echo "[compose] Creating pgdata volume (fresh install — no product data yet)..."
  podman volume create pgdata
  echo "[compose] NOTE: After startup, seed the database:"
  echo "  podman-compose exec product_catalogue python seed_data.py"
  echo "  podman-compose exec product_catalogue python generate_dataset.py"
else
  echo "[compose] Using existing pgdata volume (product data preserved)."
fi

# ── Start everything ─────────────────────────────────────────────────────────
echo ""
echo "[compose] Starting all 15 services..."
podman-compose up $BUILD_FLAG

