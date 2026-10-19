"""settlement-worker: every INTERVAL_SECONDS, settles new orders into the settlements table.

How it decides what is "new": it reads the high_water_mark (highest order id settled)
from the last SUCCESSFUL run in job_runs, then processes orders above it in small batches,
committing after each batch.

That design has a flaw you are meant to find. See docs/FAILURE_MODES.md (batch-fail).
"""
import logging
import logging.handlers
import os
import sys
import time
from datetime import datetime, timezone

import psycopg

SERVICE = "settlement-worker"
CHAOS_DIR = os.environ.get("CHAOS_DIR", "/chaos")
INTERVAL = int(os.environ.get("INTERVAL_SECONDS", "30"))
BATCH_SIZE = 10
DSN = (
    f"host={os.environ.get('DB_HOST', 'db')} port={os.environ.get('DB_PORT', '5432')} "
    f"dbname={os.environ.get('DB_NAME', 'shop')} user={os.environ.get('DB_USER', 'shop_worker')} "
    f"password={os.environ.get('DB_PASSWORD', '')} application_name={SERVICE} connect_timeout=3"
)


class KVFormatter(logging.Formatter):
    def format(self, record):
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        parts = [ts, f"level={record.levelname}", f"svc={SERVICE}", f"pid={os.getpid()}"]
        parts += [f"{k}={v}" for k, v in getattr(record, "kv", {}).items()]
        parts.append(f'msg="{record.getMessage()}"')
        line = " ".join(parts)
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


log = logging.getLogger(SERVICE)


def setup_logging():
    log.setLevel(logging.INFO)
    handlers = [logging.StreamHandler(sys.stdout)]
    if os.environ.get("LOG_FILE"):
        handlers.append(logging.handlers.WatchedFileHandler(os.environ["LOG_FILE"]))
    for h in handlers:
        h.setFormatter(KVFormatter())
        log.addHandler(h)


def kv(**fields):
    return {"kv": fields}


def flag_on(name):
    try:
        with open(os.path.join(CHAOS_DIR, "flags")) as fh:
            for line in fh:
                if line.strip().startswith(f"{name}="):
                    return line.split("=", 1)[1].strip() in ("on", "true", "1")
    except FileNotFoundError:
        pass
    return False


def run_once(conn):
    started = time.perf_counter()
    run_id = conn.execute("INSERT INTO job_runs (job, status) VALUES ('settlement', 'running') RETURNING id").fetchone()[0]
    conn.commit()
    hwm = conn.execute(
        "SELECT coalesce(max(high_water_mark), 0) FROM job_runs WHERE job = 'settlement' AND status = 'success'"
    ).fetchone()[0]
    orders = conn.execute(
        "SELECT id, total_pence, currency FROM orders WHERE id > %s ORDER BY id", (hwm,)).fetchall()
    conn.commit()
    log.info("run started", extra=kv(job="settlement", run_id=run_id, from_order=hwm + 1, pending=len(orders)))

    processed = 0
    for i in range(0, len(orders), BATCH_SIZE):
        batch = orders[i:i + BATCH_SIZE]
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO settlements (order_id, amount_pence, currency, run_id) VALUES (%s, %s, %s, %s)",
                [(o[0], o[1], o[2], run_id) for o in batch])
        processed += len(batch)
        conn.execute("UPDATE job_runs SET heartbeat_at = now(), rows_processed = %s WHERE id = %s",
                     (processed, run_id))
        conn.commit()
        if flag_on("batch_poison"):
            bad = batch[-1][0] + 1
            raise ValueError(f"unsupported currency code 'XXX' on order {bad}")

    max_id = orders[-1][0] if orders else hwm
    conn.execute("UPDATE job_runs SET status = 'success', finished_at = now(), heartbeat_at = now(), "
                 "high_water_mark = %s WHERE id = %s", (max_id, run_id))
    conn.commit()
    log.info("run finished", extra=kv(job="settlement", run_id=run_id, status="success", rows=processed,
                                      duration_ms=round((time.perf_counter() - started) * 1000)))


def main():
    setup_logging()
    log.info("worker starting", extra=kv(interval_s=INTERVAL, batch_size=BATCH_SIZE))
    try:
        while True:
            # Fresh connection per run, like a cron job would.
            with psycopg.connect(DSN) as conn:
                run_once(conn)
            time.sleep(INTERVAL)
    except Exception:
        # Crash on purpose: no cleanup, no 'failed' status. Docker restarts us (restart: on-failure).
        log.exception("worker crashed", extra=kv(job="settlement"))
        sys.exit(1)


if __name__ == "__main__":
    main()
