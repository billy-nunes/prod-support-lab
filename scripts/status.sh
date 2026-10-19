#!/usr/bin/env bash
# First 60 seconds of an incident: one screen that tells you where to look next.
# Week 1 task: read every line of this and be able to explain it. Week 3 task: improve it.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

ACCESS=logs/nginx/shop_access.log
hr() { printf '\n== %s ==\n' "$1"; }

hr "containers (look for: Exit, Restarting, unhealthy, high restart counts)"
docker compose ps --format 'table {{.Service}}\t{{.State}}\t{{.Status}}'

hr "front door"
for path in /health /ready; do
  code=$(curl -s -o /dev/null -m 5 -w '%{http_code}' "http://localhost:8080${path}")
  echo "  ${path}  -> HTTP ${code}"
done

hr "last 300 requests at nginx, by status"
if [ -f "$ACCESS" ]; then
  tail -n 300 "$ACCESS" | grep -o 'status=[0-9]*' | sort | uniq -c | sort -rn
  echo "  slowest 3 (rt = seconds):"
  tail -n 300 "$ACCESS" | awk '{for(i=1;i<=NF;i++) if($i ~ /^rt=/){split($i,a,"="); print a[2], $0}}' \
    | sort -rn | head -3 | cut -c1-160 | sed 's/^/    /'
else
  echo "  no access log yet at $ACCESS"
fi

hr "app errors in the last 300 app log lines"
if [ -f logs/app/app.log ]; then
  tail -n 300 logs/app/app.log | grep -E 'level=(ERROR|WARNING)' | grep -o 'msg="[^"]*"\|error=[A-Za-z]*' \
    | sort | uniq -c | sort -rn | head -8
fi

hr "database sessions by app and state"
docker compose exec -T db psql -U postgres -d shop -Atc \
  "SELECT rpad(coalesce(nullif(application_name,''),'(none)'),22) || rpad(coalesce(state,'(bg)'),22) || count(*)
     FROM pg_stat_activity WHERE datname = 'shop' GROUP BY application_name, state ORDER BY count(*) DESC" \
  2>&1 | sed 's/^/  /'

hr "settlement job (last 3 runs)"
docker compose exec -T db psql -U postgres -d shop -c \
  "SELECT id, status, rows_processed AS rows, started_at::time(0) AS started,
          (now() - heartbeat_at)::interval(0) AS since_heartbeat
     FROM job_runs ORDER BY id DESC LIMIT 3" 2>&1 | sed 's/^/  /'

hr "resources"
docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}' 2>/dev/null
docker compose exec -T app df -h /exports 2>/dev/null | sed 's/^/  /'
