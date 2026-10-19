#!/usr/bin/env bash
# Proves the lab works end to end: traffic flows, request IDs trace across nginx and the app,
# and one failure mode can be switched on and off. Used locally (make smoke) and in CI.
set -euo pipefail
cd "$(dirname "$0")/.."

BASE=http://localhost:8080
pass() { echo "PASS  $*"; }
fail() { echo "FAIL  $*"; exit 1; }

echo "waiting for the stack to be ready (first boot seeds data, this can take a few minutes)..."
for i in $(seq 1 120); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/ready")" = "200" ] && break
  [ "$i" = 120 ] && fail "/ready never returned 200"
  sleep 5
done
pass "/ready is 200"

if curl -sf "$BASE/health" | grep -q '"status":"ok"'; then pass "/health"; else fail "/health"; fi
if curl -sf "$BASE/products?limit=5" | grep -q '"sku"'; then pass "/products"; else fail "/products"; fi
if curl -sf "$BASE/customers/42/orders" > /dev/null; then pass "/customers/42/orders"; else fail "customer orders"; fi

# Request ID tracing: nginx generates it, the app logs it, both log lines can be found.
rid=$(curl -s -D - -o /dev/null -X POST "$BASE/checkout" -H 'Content-Type: application/json' \
        -d '{"customer_id": 2, "product_id": 1, "qty": 1}' | tr -d '\r' | awk -F': ' 'tolower($1)=="x-request-id"{print $2}')
[ -n "$rid" ] || fail "no X-Request-ID header"
sleep 2
if grep -q "req_id=$rid" logs/nginx/shop_access.log; then pass "request $rid found in nginx log"; else fail "rid not in nginx log"; fi
if grep -q "req_id=$rid" logs/app/app.log; then pass "request $rid found in app log"; else fail "rid not in app log"; fi

# Failure mode round trip. Customer 10 is bronze (id % 10 < 3), which release 1.5.0 breaks.
scripts/chaos.sh bad-release > /dev/null
sleep 2
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/checkout" -H 'Content-Type: application/json' \
         -d '{"customer_id": 10, "product_id": 1, "qty": 1}')
if [ "$code" = "500" ]; then pass "bad-release breaks bronze checkout (HTTP 500)"; else fail "expected 500, got $code"; fi
scripts/chaos.sh reset > /dev/null
for _ in $(seq 1 30); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/ready")" = "200" ] && break
  sleep 2
done
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/checkout" -H 'Content-Type: application/json' \
         -d '{"customer_id": 10, "product_id": 1, "qty": 1}')
if [ "$code" = "201" ]; then pass "reset restores checkout (HTTP 201)"; else fail "expected 201 after reset, got $code"; fi

echo "all smoke tests passed"
