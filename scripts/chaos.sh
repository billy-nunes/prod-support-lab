#!/usr/bin/env bash
# Break the shop on purpose.
#
#   scripts/chaos.sh list              show the failure modes
#   scripts/chaos.sh <mode>            trigger one mode (you know what it is: practice)
#   scripts/chaos.sh random [modes..]  trigger a hidden mode and print a vague user ticket (mock incident)
#                                      optional: limit the pool, e.g. random disk-full bad-release db-down
#   scripts/chaos.sh reveal            show what the hidden mode was and how long you took
#   scripts/chaos.sh show              print the current chaos flags
#   scripts/chaos.sh reset             put everything back (does NOT repair data damage)
#
# Written for bash 3.2 (macOS default) as well as Linux.
set -euo pipefail

cd "$(dirname "$0")/.."
STATE=chaos/state
FLAGS="$STATE/flags"
mkdir -p "$STATE"
touch "$FLAGS"

MODES="bad-release slow-upstream mem-leak conn-leak lock-hold runaway-query disk-full batch-fail db-down bad-config"

dc()   { docker compose "$@"; }
psql_admin() { dc exec -T db psql -U postgres -d shop -v ON_ERROR_STOP=1 "$@"; }

set_flag() {
  local key="$1" value="$2" tmp
  tmp="$(mktemp "$STATE/.flags.XXXXXX")"
  grep -v "^${key}=" "$FLAGS" > "$tmp" || true
  echo "${key}=${value}" >> "$tmp"
  chmod 644 "$tmp"
  mv "$tmp" "$FLAGS"   # atomic replace, so the app never reads a half-written file
}

ticket() {
  case "$1" in
    bad-release)   echo "Some customers get an error at checkout. Others say it works fine for them." ;;
    slow-upstream) echo "The whole site feels slow and checkout spins for ages before failing." ;;
    mem-leak)      echo "Customers are intermittently seeing 'Bad Gateway' pages. It comes and goes." ;;
    conn-leak)     echo "Finance says settlement figures stopped updating. The website itself seems mostly OK." ;;
    lock-hold)     echo "Checkout hangs for our best-selling products. Then everything gets slow." ;;
    runaway-query) echo "Everything slowed down in the last few minutes. Nobody has deployed anything." ;;
    disk-full)     echo "Finance's order export keeps failing. Browsing and checkout are fine." ;;
    batch-fail)    echo "Finance says settled totals today are HIGHER than actual sales. That should be impossible." ;;
    db-down)       echo "The site is down. Every page errors." ;;
    bad-config)    echo "Since this morning's config change went out, the site is erroring." ;;
  esac
}

trigger() {
  case "$1" in
    bad-release)   set_flag bad_release on ;;
    slow-upstream) set_flag payment_latency_ms 12000 ;;
    mem-leak)      set_flag mem_leak on ;;
    conn-leak)     set_flag conn_leak on ;;
    batch-fail)    set_flag batch_poison on ;;
    lock-hold)
      # A colleague's "quick manual fix" that opened a transaction and walked away.
      dc exec -d -e PGAPPNAME=ops-manual-fix db psql -U postgres -d shop \
        -c "BEGIN" \
        -c "UPDATE inventory SET qty = qty WHERE product_id <= 50" \
        -c '\! sleep 3600' ;;
    runaway-query)
      # Someone's ad hoc report with a join that explodes into billions of rows. Four copies.
      for _ in 1 2 3 4; do
        dc exec -d -e PGAPPNAME=finance-adhoc db psql -U postgres -d shop \
          -c "SELECT count(*) FROM order_items a JOIN order_items b ON a.product_id = b.product_id"
      done ;;
    disk-full)
      dc exec -T app sh -c 'mkdir -p /exports/.tmp && dd if=/dev/zero of=/exports/.tmp/buffer.bin bs=1M count=64 2>/dev/null; true' ;;
    db-down)       dc stop db ;;
    bad-config)    dc -f docker-compose.yml -f chaos/bad-config.override.yml up -d --no-deps app ;;
    *) echo "unknown mode: $1 (try: $0 list)" >&2; exit 2 ;;
  esac
}

reset_all() {
  echo "-> clearing chaos flags"
  : > "$FLAGS"
  echo "-> starting db (if stopped)"
  dc start db >/dev/null
  echo "-> waiting for db"
  for _ in $(seq 1 30); do
    dc exec -T db pg_isready -U postgres -d shop >/dev/null 2>&1 && break
    sleep 2
  done
  echo "-> ending manual / ad hoc sessions"
  psql_admin -Atc "SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity
                   WHERE application_name IN ('ops-manual-fix','finance-adhoc')" || true
  echo "-> recreating app with the committed config (clears leaks, memory and /exports)"
  dc up -d --no-deps --force-recreate app >/dev/null
  echo "-> making sure worker is running"
  dc up -d --no-deps worker >/dev/null
  rm -f "$STATE/.incident" "$STATE/.incident_started"
  echo "done. Note: reset restores SERVICE, not DATA. Duplicate settlements or stuck job_runs rows are yours to fix."
}

rot13() { tr 'A-Za-z' 'N-ZA-Mn-za-m'; }

case "${1:-}" in
  list)
    echo "Failure modes:"
    for m in $MODES; do printf "  %-14s %s\n" "$m" "$(ticket "$m")"; done ;;
  show)
    echo "Current flags ($FLAGS):"; cat "$FLAGS" ;;
  random)
    if [ -f "$STATE/.incident" ]; then
      echo "An incident is already running. Use '$0 reveal' or '$0 reset' first." >&2; exit 1
    fi
    shift
    # shellcheck disable=SC2086  # word splitting is intended here
    [ $# -gt 0 ] || set -- $MODES
    shift $(( RANDOM % $# ))
    mode="$1"
    trigger "$mode" >/dev/null 2>&1
    echo "$mode" | rot13 > "$STATE/.incident"
    date +%s > "$STATE/.incident_started"
    echo "=================================================================="
    echo " INCIDENT OPENED $(date '+%H:%M:%S')"
    echo " Ticket: \"$(ticket "$mode")\""
    echo " Start a timeline in incidents/. Run '$0 reveal' when you think you're done."
    echo "==================================================================" ;;
  reveal)
    if [ ! -f "$STATE/.incident" ]; then echo "No hidden incident running."; exit 0; fi
    mode="$(rot13 < "$STATE/.incident")"
    mins=$(( ( $(date +%s) - $(cat "$STATE/.incident_started") ) / 60 ))
    echo "It was: $mode   (time since start: ${mins} min)"
    echo "Read the matching section in docs/FAILURE_MODES.md, then run '$0 reset' if you haven't fixed it." ;;
  reset)
    reset_all ;;
  ""|-h|--help)
    sed -n '2,13p' "$0" ;;
  *)
    trigger "$1"
    echo "Triggered: $1"
    echo "User-facing symptom: $(ticket "$1")" ;;
esac
