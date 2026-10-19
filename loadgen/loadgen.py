"""loadgen: steady fake customer traffic, so failures have something to break.

Traffic mix (roughly): 45% browse products, 20% view order history, 25% checkout,
5% daily sales report, 5% finance export (rate limited to one every 30s).
Every 15 seconds it logs a summary line you can grep:
  ... svc=loadgen window_s=15 sent=58 ok=55 err4xx=1 err5xx=2 timeouts=0 p50_ms=18 p95_ms=240
"""
import json
import os
import random
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

TARGET = os.environ.get("TARGET", "http://nginx")
RPS = float(os.environ.get("RPS", "4"))
THREADS = int(os.environ.get("THREADS", "8"))
LOG_FILE = os.environ.get("LOG_FILE", "/var/log/shop/loadgen.log")
UA = "shop-loadgen/1.0"

lock = threading.Lock()
stats = {"sent": 0, "ok": 0, "err4xx": 0, "err5xx": 0, "timeouts": 0, "lat": []}
last_export = [0.0]


def emit(line):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    out = f"{ts} level=INFO svc=loadgen {line}"
    print(out, flush=True)
    try:
        with open(LOG_FILE, "a") as fh:
            fh.write(out + "\n")
    except OSError:
        pass


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(TARGET + path, data=data, method=method,
                                 headers={"User-Agent": UA, "Content-Type": "application/json"})
    started = time.perf_counter()
    kind = "ok"
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
    except urllib.error.HTTPError as exc:
        # 409 out-of-stock is normal business, not an error worth paging on
        kind = "ok" if exc.code == 409 else ("err4xx" if exc.code < 500 else "err5xx")
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        kind = "timeouts"
    with lock:
        stats["sent"] += 1
        stats[kind] += 1
        stats["lat"].append((time.perf_counter() - started) * 1000)


def discover():
    while True:
        try:
            with urllib.request.urlopen(TARGET + "/meta", timeout=5) as resp:
                meta = json.loads(resp.read())
                return meta["max_customer_id"], meta["max_product_id"]
        except Exception as exc:  # app not ready yet
            emit(f'msg="waiting for shop-api" error={type(exc).__name__}')
            time.sleep(5)


def worker(max_cust, max_prod):
    pause = THREADS / RPS
    while True:
        started = time.monotonic()
        r = random.random()
        if r < 0.45:
            call("GET", f"/products?limit={random.choice([10, 20, 50])}")
        elif r < 0.65:
            call("GET", f"/customers/{random.randint(1, max_cust)}/orders")
        elif r < 0.90:
            product = random.randint(1, 50) if random.random() < 0.7 else random.randint(1, max_prod)
            call("POST", "/checkout", {"customer_id": random.randint(1, max_cust),
                                       "product_id": product, "qty": random.choice([1, 1, 1, 2])})
        elif r < 0.95:
            call("GET", f"/reports/daily-sales?days={random.choice([1, 7, 30])}")
        else:
            with lock:
                due = time.monotonic() - last_export[0] > 30
                if due:
                    last_export[0] = time.monotonic()
            if due:
                call("POST", "/exports/orders", {})
        time.sleep(max(0.0, pause - (time.monotonic() - started)) * random.uniform(0.5, 1.5))


def reporter():
    while True:
        time.sleep(15)
        with lock:
            lat = sorted(stats["lat"])
            snap = dict(stats)
            for k in ("sent", "ok", "err4xx", "err5xx", "timeouts"):
                stats[k] = 0
            stats["lat"] = []
        p50 = round(lat[len(lat) // 2]) if lat else 0
        p95 = round(lat[int(len(lat) * 0.95) - 1]) if lat else 0
        emit(f"window_s=15 sent={snap['sent']} ok={snap['ok']} err4xx={snap['err4xx']} "
             f"err5xx={snap['err5xx']} timeouts={snap['timeouts']} p50_ms={p50} p95_ms={p95}")


def main():
    max_cust, max_prod = discover()
    emit(f'msg="starting" target={TARGET} rps={RPS} threads={THREADS} customers={max_cust} products={max_prod}')
    for _ in range(THREADS):
        threading.Thread(target=worker, args=(max_cust, max_prod), daemon=True).start()
    reporter()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
