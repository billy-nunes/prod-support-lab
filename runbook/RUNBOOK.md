# Runbook

My own on-call notes for this lab. Rule: every command that helped in an incident gets added here with one line on when to use it.

## First 60 seconds (any incident)

```bash
make status                                   # containers, /health vs /ready, status codes, DB sessions, job, resources
tail -n 300 logs/nginx/shop_access.log | grep -o 'status=[0-9]*' | sort | uniq -c
grep -E 'level=(ERROR|WARNING)' logs/app/app.log | tail -20
```

## Logs

| Question | Command |
|----------|---------|
| Errors by message | `grep level=ERROR logs/app/app.log \| grep -o 'msg="[^"]*"' \| sort \| uniq -c \| sort -rn` |
| Follow one request | `grep 'req_id=<id>' logs/nginx/shop_access.log logs/app/app.log` |
| Full traceback | `grep -A 20 'unhandled exception' logs/app/app.log \| less` |
| _add yours_ | |

## Database

```sql
-- who is connected and what are they doing
SELECT pid, application_name, state, wait_event_type, now() - xact_start AS xact_age, left(query, 60)
FROM pg_stat_activity WHERE datname = 'shop' AND state <> 'idle' ORDER BY xact_start;
```

_Add: blocking chains, top queries, table sizes, kill a session._

## Containers

_Add: restart counts, health, env, OOM, disk._

## Decision trees

_Week 3: 502 vs 503 vs 504._
