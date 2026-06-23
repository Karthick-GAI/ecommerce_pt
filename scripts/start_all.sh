#!/usr/bin/env bash
# start_all.sh — Start all 13 microservices in the background
#
# Prerequisites:
#   - Python 3.11+ on PATH
#   - PostgreSQL running + ecommerce DB created (run setup_db.sh first)
#   - .env file present at repo root (copy from .env.example)
#   - pip dependencies installed in each service directory
#
# Usage:  bash scripts/start_all.sh
#         bash scripts/start_all.sh --stop    (kill all background services)

set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"

# ── Stop mode ────────────────────────────────────────────────────────────────
if [[ "$1" == "--stop" ]]; then
  echo "Stopping all services..."
  pkill -f "uvicorn main:app" 2>/dev/null && echo "Stopped." || echo "No services running."
  exit 0
fi

# Load root .env if present
if [ -f "$ROOT/.env" ]; then
  set -a; source "$ROOT/.env"; set +a
fi

# ── Service definitions: (directory, port, service_name) ─────────────────────
# Ports match src/frontend/src/api/index.js which hardcodes localhost:800X URLs.
declare -a SERVICES=(
  "user_management:8000:user_management"
  "product_catalogue:8001:product_catalogue"
  "shopping_assistant:8002:shopping_assistant"
  "checkout_service:8003:checkout_service"
  "order_management:8004:order_management"
  "inventory_service:8005:inventory_service"
  "recommendation_engine:8006:recommendation_engine"
  "tool_calling_agent:8007:tool_calling_agent"
  "session_service:8008:session_service"
  "payment_shipping_service:8009:payment_shipping_service"
  "guardrails_service:8010:guardrails_service"
  "multi_agent_system:8011:multi_agent_system"
  "seller_portal:8012:seller_portal"
)

echo "Starting E-Commerce AI Platform services..."
echo ""

for entry in "${SERVICES[@]}"; do
  IFS=':' read -r svc_dir port svc_name <<< "$entry"
  svc_path="$ROOT/src/$svc_dir"

  if [ ! -f "$svc_path/main.py" ]; then
    echo "  [SKIP] $svc_name — $svc_path/main.py not found"
    continue
  fi

  # Copy root .env into the service directory if the service doesn't have its own
  if [ ! -f "$svc_path/.env" ] && [ -f "$ROOT/.env" ]; then
    cp "$ROOT/.env" "$svc_path/.env"
  fi

  (
    cd "$svc_path"
    # Ensure the nfr module is resolvable
    export PYTHONPATH="$ROOT/src:$PYTHONPATH"
    uvicorn main:app --host 0.0.0.0 --port "$port" --reload \
      >> "$LOG_DIR/$svc_name.log" 2>&1
  ) &

  echo "  [OK] $svc_name  →  http://localhost:$port  (logs: logs/$svc_name.log)"
done

echo ""
echo "All services started. Swagger UIs:"
for entry in "${SERVICES[@]}"; do
  IFS=':' read -r svc_dir port svc_name <<< "$entry"
  echo "  http://localhost:$port/docs  ($svc_name)"
done
echo ""
echo "To stop all:  bash scripts/start_all.sh --stop"
echo "To follow logs:  tail -f logs/user_management.log"
