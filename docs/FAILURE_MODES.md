# Failure modes

Ten things you can break on purpose, plus one problem that is always there.

How to use this page:

- **Practice mode:** `make chaos MODE=<name>`. You know what you broke, so focus on *how the evidence looks*.
- **Mock incident mode:** `make incident` (optionally `POOL="a b c"`). You only get a vague user ticket. Do not open the spoiler sections until you have run `make reveal`.
- Each mode lists **what it teaches** in the open, and keeps **where to look** and **the fix** inside a collapsed spoiler.
- `make reset` restores the *service*. It never repairs *data*. That part is on you.

Quick map:

| # | Mode | User ticket (what you hear) | Layer | Core lesson |
|---|------|-----------------------------|-------|-------------|
| 0 | slow-query (always on) | "Order history is slowish" | Postgres | Seq scans, EXPLAIN, indexes |
| 1 | bad-release | Some customers fail at checkout | App | Correlate errors with a deploy, find the pattern |
| 2 | slow-upstream | Whole site slow, checkout spins | App / dependency | Timeouts, thread starvation, 504 vs 201 |
| 3 | mem-leak | Intermittent Bad Gateway | Container | OOM kills, worker respawns, 502s |
| 4 | conn-leak | Settlements stopped, site mostly OK | App / Postgres | Connection limits, reserved slots, leaks outlive the bug |
| 5 | lock-hold | Best sellers hang, then everything | Postgres | Row locks, idle in transaction, blocker chains |
| 6 | runaway-query | Everything slower, no deploy | Postgres | CPU, parallel workers, cancel vs terminate |
| 7 | disk-full | Finance export fails | OS / filesystem | df vs du, hidden files, ENOSPC |
| 8 | batch-fail | Settled totals higher than sales | Batch / data | Crash loops, non-idempotent jobs, duplicate data |
| 9 | db-down | Site down, every page errors | Infra | Dependency failure, readiness, recovery |
| 10 | bad-config | Erroring since config change | Config / deploy | Liveness vs readiness, auth errors, rollback |

---

## 0. slow-query (always on, not a chaos mode)

**What it teaches:** reading `EXPLAIN (ANALYZE, BUFFERS)`, spotting a sequential scan on a 1M-row table, using `pg_stat_statements` to find the most expensive queries, and shipping an index safely with `CREATE INDEX CONCURRENTLY`.

The schema deliberately has no index on `orders(customer_id)` or `orders(created_at)`. Every `GET /customers/<id>/orders` reads the whole orders table. It is "fine" at low traffic, which is exactly how these problems hide in production.

<details><summary>Where to look and the fix (spoiler)</summary>

- `grep 'duration:' ` in `docker compose logs db` (anything over 50 ms is logged).
- `SELECT calls, round(mean_exec_time) AS mean_ms, left(query, 80) FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 5;`
- `EXPLAIN (ANALYZE, BUFFERS) SELECT ... WHERE customer_id = 42 ...` shows `Parallel Seq Scan on orders ... Rows Removed by Filter: ~333,000` per worker.
- Fix as a migration file: `CREATE INDEX CONCURRENTLY orders_customer_id_idx ON orders (customer_id);` then re-run EXPLAIN and compare. `CONCURRENTLY` avoids blocking writes while it builds (it cannot run inside a transaction block).
- Bonus: `order_items(order_id)` has a foreign key but no index. Find out why that matters for deletes.
</details>

---

## 1. bad-release

**Trigger:** `make chaos MODE=bad-release`
**What it teaches:** correlating an error spike with a deploy marker in the logs, and finding *which* users are affected instead of stopping at "some requests fail". Also: reading a Python traceback from the bottom up.

The app "deploys" version 1.5.0, which changed the discount table and dropped one loyalty tier.

<details><summary>Where to look and the fix (spoiler)</summary>

- `grep 'event=deploy' logs/app/app.log` gives you the exact time 1.5.0 went live. Errors start right after.
- `grep -A 15 'unhandled exception' logs/app/app.log | tail -20` ends in `KeyError: 'bronze'`.
- Prove the pattern: take a few failing `req_id`s, find their customer ids, look them up: `SELECT id, loyalty_tier FROM customers WHERE id IN (...)`. All bronze. About 30% of customers.
- Fix now: roll back (`make reset`, which logs `event=rollback`). Fix forever: tests for every tier, and canary releases.
</details>

---

## 2. slow-upstream

**Trigger:** `make chaos MODE=slow-upstream` (payment provider takes 12 s instead of ~50 ms)
**What it teaches:** how one slow dependency takes down unrelated pages; the difference between nginx's 10 s timeout and the app still finishing the work; basic capacity maths (2 workers x 4 threads = 8 requests in flight, then everything queues).

Tested result: within 30 seconds, p50 latency for *all* endpoints went from ~40 ms to ~2 s, and roughly a third of requests returned 504.

<details><summary>Where to look and the fix (spoiler)</summary>

- nginx: `grep 'status=504' logs/nginx/shop_access.log | tail`, note `urt=10.0xx` (gave up after 10 s).
- app: `grep 'upstream=payments' logs/app/app.log | tail` shows `latency_ms=12xxx` at `level=WARNING`.
- The nasty bit: find a checkout that got 504 at nginx, then look up the same `req_id` in the app log. The app logged `status=201` two seconds *later*. The customer saw an error, but the order was placed and stock was taken. That is how duplicate orders happen.
- The payment call happens *inside* the database transaction, holding a row lock on the product. Slow payments therefore also cause lock waits.
- Fix now: there is no clean fix while the provider is slow; you would fail fast (shorter client timeout) or switch provider. Fix forever: timeouts and circuit breakers on outbound calls, and move external calls outside DB transactions.
</details>

---

## 3. mem-leak

**Trigger:** `make chaos MODE=mem-leak` (a "cache" that keeps ~1 MB per request and never evicts)
**What it teaches:** watching memory grow, what a container memory limit (400 MB, or `APP_MEM_LIMIT` in `.env`) does when it is hit, and why a restart is a mitigation, not a fix.

Expected on Docker: memory climbs for 1 to 2 minutes, then the kernel kills a Gunicorn worker. The Gunicorn master starts a new one, so the container stays "up" but nginx returns bursts of 502. Then it happens again.

<details><summary>Where to look and the fix (spoiler)</summary>

- `docker stats` shows the app's MEM USAGE climbing towards 400 MiB.
- `docker compose logs app | grep -i 'SIGKILL\|out of memory\|Booting worker'`
- `grep 'status=502' logs/nginx/shop_access.log | tail` and match times to worker restarts.
- Check `docker inspect --format '{{.State.OOMKilled}} {{.RestartCount}}' prodlab-app-1` and work out why it may not say what you expect (the container did not die, a child process did).
- Turning the flag off stops the growth but does not give memory back. `make reset` (restart) does.
- Fix forever: bounded caches (LRU with a max size), memory alerts on trend not just level.
</details>

---

## 4. conn-leak

**Trigger:** `make chaos MODE=conn-leak` (the audit logger opens a new DB connection per request and never closes it)
**What it teaches:** `max_connections`, the slots Postgres reserves for superusers, how one leaky component breaks a *different* component, and that disabling buggy code does not release what it already leaked.

Tested result: all 57 non-reserved connections were used within ~25 seconds. The website stayed mostly up (its pooled connections were already open), but the settlement worker could not connect, and `psql -U shop_app` failed with `remaining connection slots are reserved for roles with the SUPERUSER attribute`.

<details><summary>Where to look and the fix (spoiler)</summary>

- `make status` shows ~56 `shop-api | idle` sessions.
- `make psql` still works because you connect as `postgres` (a superuser), so you can investigate.
- `SELECT application_name, state, count(*), min(backend_start) FROM pg_stat_activity GROUP BY 1,2;`
- `grep 'audit write failed' logs/app/app.log | head -1` and `grep 'worker crashed' logs/worker/worker.log`.
- Fix now: `docker compose restart app` (drops its connections) or `pg_terminate_backend` the idle ones. Fix forever: always use the pool (or close connections), alert on connection count.
</details>

---

## 5. lock-hold

**Trigger:** `make chaos MODE=lock-hold` (a "manual fix" session ran an UPDATE in a transaction and never committed)
**What it teaches:** row locks, `idle in transaction`, blocker chains with `pg_blocking_pids()`, and the difference between `pg_cancel_backend` and `pg_terminate_backend`.

Tested result: checkouts for products 1 to 50 queued behind the lock, used up all 8 app threads, and within ~15 seconds *every* endpoint returned 504. Killing one session fixed it instantly.

<details><summary>Where to look and the fix (spoiler)</summary>

- Postgres log: `process N still waiting for ShareLock on transaction T after 1000 ms` followed by `Process holding the lock: P`.
- `SELECT pid, application_name, state, wait_event_type, now() - xact_start AS xact_age, left(query, 60) FROM pg_stat_activity WHERE state <> 'idle' ORDER BY xact_start;`
- `SELECT pid, pg_blocking_pids(pid) FROM pg_stat_activity WHERE cardinality(pg_blocking_pids(pid)) > 0;` Note some sessions are blocked by *other waiters*, not by the root. Follow the chain to the root.
- Root: `application_name = ops-manual-fix`, `state = idle in transaction`, transaction age growing.
- Fix now: `SELECT pg_terminate_backend(<pid>);` (cancel will not work: it is idle, there is no running query to cancel). Fix forever: `idle_in_transaction_session_timeout`, and no ad hoc writes in prod without a reviewed script.
</details>

---

## 6. runaway-query

**Trigger:** `make chaos MODE=runaway-query` (four copies of an ad hoc report with a join that produces billions of rows)
**What it teaches:** finding a CPU hog, parallel query workers, `pg_cancel_backend`, and `statement_timeout`. This one is a *slowdown*, not an outage, which makes it easy to dismiss.

<details><summary>Where to look and the fix (spoiler)</summary>

- `docker stats`: the db container is at high CPU.
- `docker compose exec db top` or `ps aux`: several `postgres` processes at 100%.
- `SELECT pid, application_name, backend_type, now() - query_start AS runtime, left(query, 60) FROM pg_stat_activity WHERE state = 'active' ORDER BY query_start;` Parallel workers show the same `application_name` as their leader.
- Fix now: `pg_cancel_backend(pid)` on the client backends (parallel workers stop with them). Fix forever: `ALTER ROLE ... SET statement_timeout`, a read replica for reports.
</details>

---

## 7. disk-full

**Trigger:** `make chaos MODE=disk-full` (something filled the 64 MB export volume)
**What it teaches:** `df` vs `du`, hidden dot-directories, `find -size`, and how an `ENOSPC` error surfaces in an app. Only one feature breaks, so the rest of the site looks fine.

<details><summary>Where to look and the fix (spoiler)</summary>

- `grep 'No space left' logs/app/app.log`, and `status=500` on `path=/exports/orders`.
- `docker compose exec app df -h /exports` shows 100%. `ls /exports` looks almost empty. Why?
- `docker compose exec app du -ah /exports | sort -h | tail` or `find /exports -size +1M` finds `/exports/.tmp/buffer.bin`.
- Fix now: remove the file. Fix forever: alert on disk usage, clean up temp files, separate volumes for scratch data.
</details>

---

## 8. batch-fail

**Trigger:** `make chaos MODE=batch-fail` (the settlement job hits a "bad record" after committing its first batch)
**What it teaches:** crash loops and restart counts, stuck job status rows, *non-idempotent* batch jobs, and finding duplicate data with SQL. Also: error messages can point at the wrong thing.

The job reads its starting point from the last *successful* run. It commits every 10 rows. When it crashes, Docker restarts it, it starts from the same point, and re-inserts rows it already committed. Every restart adds more duplicates.

<details><summary>Where to look and the fix (spoiler)</summary>

- `docker compose ps` (worker restarting), `docker inspect --format '{{.RestartCount}}' prodlab-worker-1`.
- `grep -B2 'ValueError' logs/worker/worker.log`. Check the order id it names: `SELECT currency FROM orders WHERE id = ...`. It is GBP. The message is misleading; trust data over messages.
- `SELECT status, count(*) FROM job_runs GROUP BY 1;` several rows stuck in `running`.
- Duplicates: `SELECT order_id, count(*) FROM settlements GROUP BY order_id HAVING count(*) > 1;`
- Fix now: `make reset` stops the crash loop. Then repair data inside a transaction: delete duplicates keeping the lowest id per order (try `ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY id)`), check counts, then COMMIT. Mark stuck runs `failed`.
- Fix forever: a unique constraint on `settlements(order_id)` plus `INSERT ... ON CONFLICT DO NOTHING`, and alerting on job heartbeat age.
</details>

---

## 9. db-down

**Trigger:** `make chaos MODE=db-down`
**What it teaches:** what a dependency outage looks like from each layer, how quickly the app recovers on its own, and why `/health` and `/ready` are different.

<details><summary>Where to look and the fix (spoiler)</summary>

- `make status`: db `exited`, `/health` 200, `/ready` 503.
- `grep PoolTimeout logs/app/app.log | tail -3`. The pool waits 5 s before giving up, so every request takes 5 s and then fails.
- Fix now: `docker compose start db`. Watch the app recover by itself within seconds (tested). Note how long it took and put it in your incident notes.
</details>

---

## 10. bad-config

**Trigger:** `make chaos MODE=bad-config` (a config change sets a new DB password in the app, but nobody changed it in Postgres)
**What it teaches:** liveness vs readiness (Docker says the app is *healthy* while it cannot serve anything), reading Postgres auth errors, diffing config, and rolling back.

<details><summary>Where to look and the fix (spoiler)</summary>

- `make status`: `/health` 200 but `/ready` 503. The Docker healthcheck uses `/health`, so `docker compose ps` says healthy. That is a monitoring gap.
- `grep 'logger=psycopg.pool' logs/app/app.log | tail -1` and `docker compose logs db | grep 'password authentication failed'`.
- `docker compose exec app env | grep -E 'DB_|APP_VERSION'` shows version 1.4.2 and a password that differs from `docker-compose.yml`.
- Fix now: roll back to the committed config: `docker compose up -d --force-recreate app` (or `make reset`). Fix forever: change secrets on both sides in one change, and point the healthcheck at something that proves the app can work.
</details>
