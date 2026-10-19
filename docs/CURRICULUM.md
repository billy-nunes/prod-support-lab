# 6-week curriculum

45 minutes a day. Days 1 to 6 are exercises, day 7 is a mock incident. Every day ends with a commit, so the repo history *is* the learning log.

**Rules**

- Timebox. At 35 minutes, stop and write down where you got to. Unfinished is fine; unrecorded is not.
- Every new command you find useful goes into `runbook/RUNBOOK.md` with one line on when to use it.
- Mock incidents: start a timer, open `incidents/TEMPLATE.md` as a new file, write the timeline *as you go*. If you have not found it in 30 minutes, `make reveal` and study the answer. That still counts.
- Commit message format: `wk1d3: trace a request through nginx and app`.

---

## Week 1: Logs, containers and the front door

| Day | Exercise | Done when |
|-----|----------|-----------|
| 1 | `make up`. Watch the seed with `docker compose logs -f db`. Run `docker compose ps`, open http://localhost:8080/products. Draw the request path (loadgen, nginx, app, db, worker) in your own words in `notes/architecture.md`. | You can say what each service does and which port and log file belongs to it. |
| 2 | Logs with grep and awk on `logs/nginx/shop_access.log`: count by status, requests per minute (`cut -c1-16 \| uniq -c`), the 5 slowest requests by `rt=`. | 3 one-liners saved in the runbook. |
| 3 | Trace one request: pick a `req_id` from nginx, find it in the app log. Then find a `status=409` and explain why "out of stock" is not an incident. | You can explain `rt` vs `urt` vs `dur_ms` vs `db_ms`. |
| 4 | Containers as processes: `docker stats`, `docker compose exec app ps aux`, `env`, `docker inspect` (health, restarts, mounts). Hit `/health` and `/ready` and explain the difference. | Runbook entry: "is it the container or the app?" |
| 5 | Practice `disk-full`, knowing what it is. Use `df`, `du`, `find -size`, `ls -la`. Fix it. | You can explain why `ls` looked empty while `df` said 100%. |
| 6 | Read `scripts/status.sh` line by line and annotate it. Practice `bad-release`: find the deploy marker and prove which customers are affected with SQL. | First real incident write-up committed. |
| 7 | **Mock incident:** `make incident POOL="disk-full bad-release db-down"` | `incidents/INC-00x.md` with timeline, root cause, fix. |

## Week 2: Postgres for support

| Day | Exercise | Done when |
|-----|----------|-----------|
| 1 | psql tour: `\dt+`, `\d+ orders`, `\di`, table sizes with `pg_size_pretty(pg_total_relation_size(...))`, estimated vs exact row counts. | Runbook has your "size of everything" query. |
| 2 | `pg_stat_activity`: states (`active`, `idle`, `idle in transaction`), `wait_event_type`, `application_name`. Write one query you would run first in any DB incident. | Query saved as `sql/first_look.sql`. |
| 3 | Find the slow query: `pg_stat_statements` top 5 by total time, then `EXPLAIN (ANALYZE, BUFFERS)` on the customer orders query. | You can read "Parallel Seq Scan" and "Rows Removed by Filter" out loud and explain them. |
| 4 | Fix it: write `db/migrations/001_orders_customer_id_idx.sql` using `CREATE INDEX CONCURRENTLY`, apply it, compare before/after timings and plans. | Before/after numbers in `notes/indexing.md`. |
| 5 | Practice `lock-hold`: find the root blocker with `pg_blocking_pids`, try `pg_cancel_backend` (see why it fails), then terminate. Set `idle_in_transaction_session_timeout` for the postgres role and test it. | Runbook entry: "checkout hangs". |
| 6 | Practice `runaway-query`: find it with `docker stats` and `pg_stat_activity`, cancel it, set a `statement_timeout` on a role. Bonus: find the temp file messages in the db log. | You can explain cancel vs terminate. |
| 7 | **Mock incident:** `make incident POOL="lock-hold runaway-query bad-release disk-full"` | Incident write-up committed. |

## Week 3: The app and HTTP layer

| Day | Exercise | Done when |
|-----|----------|-----------|
| 1 | Status codes: write what 499, 500, 502, 503 and 504 mean *in this stack*, and which log proves each. Practice `slow-upstream`: find a 504 at nginx whose `req_id` is a 201 in the app. | You can explain why the customer saw an error but was charged. |
| 2 | Capacity maths: 2 workers x 4 threads = 8 slots. With 12 s payments, how many checkouts per second fill it? Write a short proposal: timeouts, and move the payment call out of the DB transaction. | `notes/capacity.md` committed. |
| 3 | Practice `conn-leak`: connection counts per app, reserved superuser slots, why the website survives but the worker dies, why turning the flag off is not enough. | Runbook entry: "too many clients". |
| 4 | Practice `mem-leak`: watch `docker stats`, find worker SIGKILLs, match them to 502 bursts. Check `OOMKilled` and explain what it shows. | You can explain mitigation (restart) vs fix (bounded cache). |
| 5 | Practice `bad-config`: compare running env with `docker-compose.yml`, find the auth failure in the db log, roll back. Write a 5-line pre-change checklist. | Checklist in the runbook. |
| 6 | Build a 502/503/504 decision tree for this stack in the runbook (which log, which command, what each answer means). | Decision tree committed. |
| 7 | **Mock incident:** `make incident POOL="slow-upstream conn-leak mem-leak bad-config lock-hold"` | Incident write-up committed. |

## Week 4: Batch jobs, data integrity and backups

| Day | Exercise | Done when |
|-----|----------|-----------|
| 1 | Read `worker/worker.py`. Write a SQL check that says "settlement is healthy / stale" from `job_runs` (heartbeat age, last success age). | `sql/job_health.sql` committed. |
| 2 | Practice `batch-fail`: crash loop, restart count, stuck `running` rows, duplicates with `GROUP BY ... HAVING`, then the same with `ROW_NUMBER()` in a CTE. | You can show the duplicate count and explain how it grew. |
| 3 | Repair the data safely: `BEGIN`, delete duplicates with a CTE, check counts, mark stuck runs `failed`, `COMMIT`. Then a migration adding a unique constraint, and make the worker insert with `ON CONFLICT DO NOTHING`. | `db/migrations/002_...sql` and the worker change committed. |
| 4 | Backups: `pg_dump -Fc`, restore into a new database `shop_restore`, compare row counts. Time both. | Runbook entry with real timings. |
| 5 | Restore drill: delete some orders "by accident" and restore just that table from the dump. Write down your RPO and RTO for this setup. | `notes/backup-restore.md` committed. |
| 6 | Schedule it: a cron job (or a loop script) that takes a nightly dump and runs the job health check, logging to a file. | Script plus cron line in the repo. |
| 7 | **Mock incident:** `make incident` (all ten modes). | Incident write-up committed. |

## Week 5: Kubernetes with kind

| Day | Exercise | Done when |
|-----|----------|-----------|
| 1 | Install `kind` and `kubectl`, create a cluster, build the app and worker images, `kind load docker-image`. | `kubectl get nodes` works and images are loaded. |
| 2 | Write `k8s/db.yaml`: Postgres with a PVC, init scripts from a ConfigMap, `SEED_SCALE=0.05`. | Data seeded, `kubectl exec` into psql works. |
| 3 | Write `k8s/app.yaml`: Deployment and Service, credentials from a Secret, liveness on `/health`, readiness on `/ready`. Port-forward and test. | Pods Ready; you can explain what each probe does on failure. |
| 4 | Break it: change the Secret's password and restart the Deployment. Compare with bad-config in Docker. Use `get`, `describe`, `logs`, `logs --previous`, `get events`. | Runbook: the kubectl triage order you will use. |
| 5 | Resource limits: set a memory limit, turn on mem-leak (mount the flags as a ConfigMap), and watch `OOMKilled` in `kubectl describe pod`. | You can explain requests vs limits. |
| 6 | Rollouts: deploy a bad image tag, see `ImagePullBackOff`, `kubectl rollout undo`. Then write `k8s/break.sh` that picks one of 4 breakages at random and hides the answer (copy the pattern from `scripts/chaos.sh`). | `k8s/break.sh` committed. |
| 7 | **Mock incident:** run `k8s/break.sh`, diagnose with kubectl only. | Incident write-up committed. |

## Week 6: Observability and on-call

| Day | Exercise | Done when |
|-----|----------|-----------|
| 1 | `make obs`. Check Prometheus targets at http://localhost:9090. PromQL: request rate and error ratio from `shop_http_requests_total`. | 2 queries saved in `observability/queries.md`. |
| 2 | Latency: `histogram_quantile(0.95, ...)` on `shop_http_request_duration_seconds`. Postgres exporter: connections and locks. Trigger slow-upstream and watch the graphs move. | You can predict what each chaos mode does to each graph. |
| 3 | Grafana (http://localhost:3000): a dashboard with the 4 golden signals. Export the JSON to `observability/dashboards/`. | Dashboard JSON committed. |
| 4 | Alerts: write Prometheus rules for error ratio > 5% for 2m, p95 > 1s, DB connections > 50. Trigger chaos and confirm they fire. | `observability/alerts.yml` committed and loaded. |
| 5 | SLOs: define a checkout availability SLO (for example 99.5% over 28 days) and work out the error budget in minutes. Which mock incidents would have blown it? | `notes/slo.md` committed. |
| 6 | Rewrite your best incident as a blameless postmortem: impact, timeline, root cause, contributing factors, actions with owners. | Postmortem committed. |
| 7 | **Final mock incident:** `make incident`. Start from dashboards and alerts only, then logs. Full postmortem. Update the README "What I learned" section. | Final postmortem and README committed. |
