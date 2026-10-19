"""shop-api: a small order API with realistic bugs you can switch on.

Every request logs one key=value line, so you can grep and awk it:
  2026-10-19T09:41:02.123Z level=INFO svc=shop-api version=1.4.1 req_id=ab12 method=GET path=/products status=200 dur_ms=12 db_ms=5

Chaos flags are read from $CHAOS_DIR/flags (key=value lines), written by scripts/chaos.sh.
"""
import csv
import logging
import logging.handlers
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timezone

import psycopg
from flask import Flask, g, jsonify, request
from werkzeug.exceptions import HTTPException
from prometheus_client import (CONTENT_TYPE_LATEST, CollectorRegistry, Counter,
                               Histogram, generate_latest, multiprocess)
from psycopg_pool import ConnectionPool

SERVICE = "shop-api"
GOOD_VERSION = os.environ.get("APP_VERSION", "1.4.1")
BAD_VERSION = "1.5.0"
CHAOS_DIR = os.environ.get("CHAOS_DIR", "/chaos")
EXPORT_DIR = os.environ.get("EXPORT_DIR", "/exports")

DSN = (
    f"host={os.environ.get('DB_HOST', 'db')} port={os.environ.get('DB_PORT', '5432')} "
    f"dbname={os.environ.get('DB_NAME', 'shop')} user={os.environ.get('DB_USER', 'shop_app')} "
    f"password={os.environ.get('DB_PASSWORD', '')} application_name=shop-api connect_timeout=3"
)


# --------------------------------------------------------------------------- logging
class KVFormatter(logging.Formatter):
    def format(self, record):
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        fields = getattr(record, "kv", {})
        parts = [ts, f"level={record.levelname}", f"svc={SERVICE}", f"version={current_version()}",
                 f"pid={os.getpid()}"]
        if "req_id" not in fields:
            try:
                parts.append(f"req_id={g.req_id}")
            except RuntimeError:  # outside a request
                pass
        for k, v in fields.items():
            parts.append(f"{k}={v}")
        if record.name != SERVICE:
            parts.append(f"logger={record.name}")
        parts.append(f'msg="{record.getMessage()}"')
        line = " ".join(parts)
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


log = logging.getLogger(SERVICE)


def setup_logging():
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = KVFormatter()
    handlers = [logging.StreamHandler(sys.stdout)]
    log_file = os.environ.get("LOG_FILE")
    if log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        handlers.append(logging.handlers.WatchedFileHandler(log_file))
    for h in handlers:
        h.setFormatter(fmt)
        root.addHandler(h)



def kv(**fields):
    return {"kv": fields}


# --------------------------------------------------------------------------- chaos flags
_flags = {"mtime": None, "values": {}}
_flags_lock = threading.Lock()


def flags():
    path = os.path.join(CHAOS_DIR, "flags")
    try:
        mtime = os.stat(path).st_mtime
    except FileNotFoundError:
        return {}
    with _flags_lock:
        if mtime != _flags["mtime"]:
            values = {}
            with open(path) as fh:
                for line in fh:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        values[k.strip()] = v.strip()
            _flags.update(mtime=mtime, values=values)
        return _flags["values"]


def flag_on(name):
    return flags().get(name, "off") in ("on", "true", "1")


_last_logged_version = None


def current_version():
    return BAD_VERSION if flag_on("bad_release") else GOOD_VERSION


def note_version_change():
    """Log once per worker process when the running 'release' changes, like a deploy marker."""
    global _last_logged_version
    v = current_version()
    if v != _last_logged_version:
        if _last_logged_version is None:
            log.info("service started", extra=kv(event="startup"))
        elif v == BAD_VERSION:
            log.info("release deployed", extra=kv(event="deploy", previous=_last_logged_version))
        else:
            log.info("release rolled back", extra=kv(event="rollback", previous=_last_logged_version))
        _last_logged_version = v


# --------------------------------------------------------------------------- metrics
REQUESTS = Counter("shop_http_requests_total", "HTTP requests", ["method", "endpoint", "status"])
LATENCY = Histogram("shop_http_request_duration_seconds", "Request latency", ["endpoint"],
                    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30))

# --------------------------------------------------------------------------- app + db
setup_logging()
app = Flask(__name__)
pool = ConnectionPool(
    DSN,
    min_size=2,
    max_size=int(os.environ.get("DB_POOL_MAX", "8")),
    timeout=5,
    max_idle=60,
    check=ConnectionPool.check_connection,
    open=True,
    name="shop-pool",
)

# These two lists are the "bugs". They only grow while the matching chaos flag is on,
# and they are NOT emptied when the flag goes off. Only a restart frees them.
_response_cache = []      # mem_leak: a cache that never evicts
_audit_connections = []   # conn_leak: audit writer that never closes its connection


class Timer:
    def __init__(self):
        self.ms = 0.0

    def __enter__(self):
        self._t = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.ms += (time.perf_counter() - self._t) * 1000


def db():
    """Borrow a pooled connection. Waiting for a free connection counts towards db_ms."""
    return pool.connection()


@app.before_request
def start_request():
    g.start = time.perf_counter()
    g.req_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
    g.db_timer = Timer()
    note_version_change()
    if flag_on("mem_leak"):
        # "Cache" ~1 MB per request, forever.
        _response_cache.append(b"x" * (1024 * 1024))


@app.after_request
def finish_request(resp):
    if flag_on("conn_leak") and request.path.startswith(("/checkout", "/products", "/customers")):
        write_audit_event(f"{request.method} {request.path}")
    dur_ms = (time.perf_counter() - g.start) * 1000
    endpoint = request.url_rule.rule if request.url_rule else "unmatched"
    level = logging.ERROR if resp.status_code >= 500 else (logging.WARNING if resp.status_code >= 400 else logging.INFO)
    log.log(level, "request complete", extra=kv(
        method=request.method, path=request.path, status=resp.status_code,
        dur_ms=round(dur_ms, 1), db_ms=round(g.db_timer.ms, 1)))
    REQUESTS.labels(request.method, endpoint, resp.status_code).inc()
    LATENCY.labels(endpoint).observe(dur_ms / 1000)
    resp.headers["X-Request-ID"] = g.req_id
    return resp


@app.errorhandler(Exception)
def unhandled(exc):
    if isinstance(exc, HTTPException):  # 404, 405 etc. are not crashes
        return jsonify(error=exc.name, req_id=g.req_id), exc.code
    log.error("unhandled exception", exc_info=exc, extra=kv(error=type(exc).__name__))
    status = 503 if isinstance(exc, (psycopg.OperationalError,)) or type(exc).__name__ == "PoolTimeout" else 500
    return jsonify(error=type(exc).__name__, req_id=g.req_id), status


def write_audit_event(event):
    """Buggy audit writer: opens its own connection per call and keeps it open."""
    try:
        conn = psycopg.connect(DSN)
        _audit_connections.append(conn)  # BUG: never closed
        conn.execute("INSERT INTO audit_log (event, req_id) VALUES (%s, %s)", (event, g.req_id))
        conn.commit()
    except Exception as exc:  # the request still succeeds, so this is easy to miss
        log.error("audit write failed", extra=kv(error=type(exc).__name__,
                                                  detail=str(exc).strip().replace("\n", " ")[:200]))


# --------------------------------------------------------------------------- endpoints
@app.get("/health")
def health():
    """Liveness: is the process up? Deliberately does NOT touch the database."""
    return jsonify(status="ok", version=current_version())


@app.get("/ready")
def ready():
    """Readiness: can we serve real traffic (database reachable)?"""
    with db() as conn, g.db_timer:
        conn.execute("SELECT 1")
    return jsonify(status="ready")


@app.get("/meta")
def meta():
    with db() as conn, g.db_timer:
        row = conn.execute("SELECT (SELECT max(id) FROM customers), (SELECT max(id) FROM products)").fetchone()
    return jsonify(max_customer_id=row[0], max_product_id=row[1])


@app.get("/products")
def products():
    limit = min(int(request.args.get("limit", 20)), 100)
    with db() as conn, g.db_timer:
        rows = conn.execute(
            """SELECT p.id, p.sku, p.name, p.price_pence, i.qty
                 FROM products p JOIN inventory i ON i.product_id = p.id
                ORDER BY p.id LIMIT %s""", (limit,)).fetchall()
    return jsonify([dict(id=r[0], sku=r[1], name=r[2], price_pence=r[3], in_stock=r[4]) for r in rows])


@app.get("/customers/<int:customer_id>/orders")
def customer_orders(customer_id):
    # No index on orders.customer_id, so this scans the whole orders table every time.
    with db() as conn, g.db_timer:
        rows = conn.execute(
            """SELECT id, status, total_pence, created_at FROM orders
                WHERE customer_id = %s ORDER BY created_at DESC LIMIT 20""", (customer_id,)).fetchall()
    return jsonify([dict(id=r[0], status=r[1], total_pence=r[2], created_at=r[3].isoformat()) for r in rows])


@app.get("/reports/daily-sales")
def daily_sales():
    days = min(int(request.args.get("days", 7)), 90)
    with db() as conn, g.db_timer:
        rows = conn.execute(
            """SELECT date_trunc('day', created_at)::date AS day, count(*), sum(total_pence)
                 FROM orders WHERE created_at > now() - make_interval(days => %s)
                GROUP BY 1 ORDER BY 1""", (days,)).fetchall()
    return jsonify([dict(day=r[0].isoformat(), orders=r[1], revenue_pence=int(r[2])) for r in rows])


# Discount table. Release 1.5.0 "forgot" bronze customers.
PROMO_RATES = {"1.4.1": {"bronze": 0.00, "silver": 0.05, "gold": 0.10},
               "1.5.0": {"silver": 0.05, "gold": 0.12}}


def apply_discount(total_pence, tier):
    rates = PROMO_RATES.get(current_version(), PROMO_RATES["1.4.1"])
    return int(total_pence * (1 - rates[tier]))


def call_payment_provider(amount_pence):
    """Pretend HTTP call to an external payment provider. Normally 30-80 ms."""
    started = time.perf_counter()
    extra = int(flags().get("payment_latency_ms", "0") or 0)
    time.sleep((30 + (uuid.uuid4().int % 50) + extra) / 1000)
    latency = round((time.perf_counter() - started) * 1000)
    lvl = logging.WARNING if latency > 2000 else logging.INFO
    log.log(lvl, "payment authorised", extra=kv(upstream="payments", latency_ms=latency, amount_pence=amount_pence))


@app.post("/checkout")
def checkout():
    body = request.get_json(force=True, silent=True) or {}
    customer_id = int(body.get("customer_id", 0))
    product_id = int(body.get("product_id", 0))
    qty = max(1, int(body.get("qty", 1)))
    with db() as conn, g.db_timer:
        with conn.transaction():
            cust = conn.execute("SELECT loyalty_tier FROM customers WHERE id = %s", (customer_id,)).fetchone()
            if not cust:
                return jsonify(error="unknown customer"), 404
            # Row lock on the product's stock. Held until the transaction commits.
            stock = conn.execute(
                "SELECT i.qty, p.price_pence FROM inventory i JOIN products p ON p.id = i.product_id "
                "WHERE i.product_id = %s FOR UPDATE OF i", (product_id,)).fetchone()
            if not stock:
                return jsonify(error="unknown product"), 404
            if stock[0] < qty:
                log.warning("out of stock", extra=kv(product_id=product_id, requested=qty, available=stock[0]))
                return jsonify(error="out of stock"), 409
            total = apply_discount(stock[1] * qty, cust[0])
            # Design smell worth spotting: an external call INSIDE the transaction, while holding the lock.
            call_payment_provider(total)
            conn.execute("UPDATE inventory SET qty = qty - %s, updated_at = now() WHERE product_id = %s",
                         (qty, product_id))
            order_id = conn.execute(
                "INSERT INTO orders (customer_id, status, currency, total_pence, shipping_address) "
                "VALUES (%s, 'paid', 'GBP', %s, 'n/a') RETURNING id", (customer_id, total)).fetchone()[0]
            conn.execute("INSERT INTO order_items (order_id, product_id, qty, unit_price_pence) VALUES (%s, %s, %s, %s)",
                         (order_id, product_id, qty, stock[1]))
    log.info("order placed", extra=kv(order_id=order_id, customer_id=customer_id, product_id=product_id,
                                      total_pence=total))
    return jsonify(order_id=order_id, total_pence=total), 201


@app.post("/exports/orders")
def export_orders():
    """Finance export: writes the latest 20k orders to CSV, keeps the 5 newest files."""
    os.makedirs(EXPORT_DIR, exist_ok=True)
    name = f"orders-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}.csv"
    path = os.path.join(EXPORT_DIR, name)
    with db() as conn, g.db_timer:
        rows = conn.execute("SELECT id, customer_id, status, currency, total_pence, created_at "
                            "FROM orders ORDER BY id DESC LIMIT 20000").fetchall()
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["id", "customer_id", "status", "currency", "total_pence", "created_at"])
        writer.writerows(rows)
    exports = sorted(f for f in os.listdir(EXPORT_DIR) if f.startswith("orders-"))
    for old in exports[:-5]:
        os.remove(os.path.join(EXPORT_DIR, old))
    log.info("export written", extra=kv(file=name, rows=len(rows)))
    return jsonify(file=name, rows=len(rows)), 201


@app.get("/metrics")
def metrics():
    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)
    return generate_latest(registry), 200, {"Content-Type": CONTENT_TYPE_LATEST}
