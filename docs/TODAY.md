# Ship it today: build, break, write up, push

About 4.5 hours of focused work, in blocks. Each block ends with a commit, so your GitHub history shows the learning, not one big dump.

The goal for tonight is not "finished lab". It is a public repo where someone can run `make up`, and where **you** can explain every file and point to incident write-ups you did yourself.

---

## Block 0: Set up (15 min)

1. Docker Desktop: Settings > Resources, give it at least 4 GB RAM (6 GB is comfortable) and 4 CPUs.
2. Unzip the repo somewhere sensible, `cd` into it.
3. `git init && git add . && git commit -m "Initial lab scaffold"`
4. `make up`, then `docker compose logs -f db` and watch the seed. It ends with `database system is ready to accept connections` after a restart. Ctrl+C to stop watching.
5. `make status`. Everything should be running, `/ready` 200.

Stuck? `docker compose ps` and `docker compose logs <service>` are your first two commands. That is also lesson one.

## Block 1: Understand what you are about to publish (45 min)

Read these files in this order and answer the questions in `notes/architecture.md` (create it):

| File | Answer this |
|------|-------------|
| `docker-compose.yml` | Which ports are exposed to your laptop? Why does `app` wait for `db` to be *healthy*? What does `mem_limit` do? |
| `db/init/01_schema.sql` | Which indexes are missing on purpose? Why add foreign keys *after* loading data? |
| `app/app.py` (skim) | What is the difference between `/health` and `/ready`? Where does the payment call happen, and why is that a problem? |
| `nginx/nginx.conf` | What do `rt` and `urt` mean? What happens at 10 seconds? |
| `worker/worker.py` | How does it decide which orders are new? What happens if it crashes halfway? |
| `scripts/chaos.sh` | How does a flag get from your laptop into the running app? |

Then: `make logs` for 2 minutes and just watch. Find one `req_id` in both the nginx and app logs.

```bash
git add notes && git commit -m "wk1d1: map the stack and trace a request"
```

## Block 2: First practice incident, bad-release (45 min)

1. `cp incidents/TEMPLATE.md incidents/INC-001-bad-release.md`
2. Note the time. `make chaos MODE=bad-release`
3. Investigate as if you did not know: `make status`, then grep the app log for errors. Find the deploy marker. Work out which customers fail (hint: look them up in the database with `make psql`).
4. Fix with `make reset`. Confirm `event=rollback` in the log and that errors stop.
5. Fill in the template properly. Paste the evidence lines.

```bash
git add incidents && git commit -m "INC-001: checkout errors for bronze customers after 1.5.0"
```

## Block 3: Fix a real performance problem (45 min)

1. `make psql`, then:
   ```sql
   SELECT calls, round(mean_exec_time) AS mean_ms, left(query, 70) FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 5;
   EXPLAIN (ANALYZE, BUFFERS) SELECT id, status, total_pence, created_at FROM orders WHERE customer_id = 42 ORDER BY created_at DESC LIMIT 20;
   ```
2. Save the plan and timing to `notes/indexing.md`.
3. Create `db/migrations/001_orders_customer_id_idx.sql`:
   ```sql
   CREATE INDEX CONCURRENTLY IF NOT EXISTS orders_customer_id_idx ON orders (customer_id);
   ```
   Apply it (command in `db/migrations/README.md`). Re-run EXPLAIN. Record before and after.
4. Write 3 sentences: why it was slow, why `CONCURRENTLY`, what the cost of an index is.

```bash
git add db/migrations notes && git commit -m "wk2: index orders.customer_id, seq scan to index scan"
```

## Lunch

## Block 4: Mock incident, blind (45 min)

1. `cp incidents/TEMPLATE.md incidents/INC-002-mock.md`
2. `make incident POOL="disk-full bad-release db-down"` and read only the ticket.
3. 30 minutes to find and fix it. Write the timeline as you go. `make reveal` at the end (or at 30 minutes).
4. Be honest in "What I'd do differently". That section is what an interviewer will want to talk about.

```bash
git add incidents && git commit -m "INC-002: mock incident write-up"
```

## Block 5: Publish (45 min)

1. Edit `README.md`:
   - Fill in **What I've learned so far** with 3 to 5 real bullets from today.
   - Check **How this was built** is accurate.
2. `LICENSE`: replace `YOUR NAME`.
3. Create an empty public repo on GitHub called `prod-support-lab` (no README, no licence, it must be empty). Then:
   ```bash
   git branch -M main
   git remote add origin git@github.com:<your-username>/prod-support-lab.git
   git push -u origin main
   ```
4. Open the **Actions** tab and check `lab-ci` goes green (lint, then the stack starts with a small data set and the smoke test runs). If it goes red, that is today's bonus incident: read the logs, fix, push.
5. Pin the repo on your GitHub profile. Add one line to your CV under projects.

```bash
git commit -am "README: what I learned on day 1" && git push
```

**Done for today.** Tomorrow is Week 1 Day 2 in `docs/CURRICULUM.md`.

---

## If something goes wrong

| Problem | Try |
|---------|-----|
| Port 8080 or 55432 already in use | `lsof -i :8080`, stop the other thing, or change the port in `docker-compose.yml` |
| Seed is very slow or the db container restarts | Give Docker more RAM, or `make nuke && make up SEED_SCALE=0.2` |
| `Permission denied` writing logs | `make prep` (fixes folder permissions) |
| You changed `db/init/` and nothing happened | Init scripts only run on an empty volume: `make nuke && make up` |
| Everything is weird | `make reset`. Still weird: `make nuke && make up` |
