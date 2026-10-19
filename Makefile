SHELL := /bin/bash
# Pass SEED_SCALE on the command line (make up SEED_SCALE=0.05) or set it in .env. Default is 1.
ifdef SEED_SCALE
export SEED_SCALE
endif

.PHONY: help prep up down nuke status logs psql chaos incident reveal reset smoke obs

help:            ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-10s %s\n", $$1, $$2}'

prep:
	@mkdir -p logs/app logs/nginx logs/worker logs/loadgen chaos/state
	@touch chaos/state/flags
	@chmod -R a+rwX logs chaos/state   # containers run as a non-root user and must write here

up: prep         ## build and start the lab (SEED_SCALE=0.05 for small machines)
	docker compose up -d --build
	@echo "First boot seeds data. Watch it with: docker compose logs -f db"
	@echo "Then: make status   |   shop: http://localhost:8080/products"

down:            ## stop containers, keep the database
	docker compose down

nuke:            ## stop and DELETE the database volume (re-seeds on next up)
	docker compose --profile obs down -v
	rm -f logs/*/*.log chaos/state/flags chaos/state/.incident*

status:          ## one-screen health check
	@scripts/status.sh

logs:            ## follow all four log files on your laptop
	tail -F logs/nginx/shop_access.log logs/app/app.log logs/worker/worker.log logs/loadgen/loadgen.log

psql:            ## open psql as the postgres superuser
	docker compose exec db psql -U postgres -d shop

chaos:           ## trigger a mode: make chaos MODE=bad-release  (make chaos MODE=list)
	@scripts/chaos.sh $(MODE)

incident:        ## hidden random incident. Limit the pool: make incident POOL="disk-full db-down"
	@scripts/chaos.sh random $(POOL)

reveal:          ## show what the hidden incident was
	@scripts/chaos.sh reveal

reset:           ## undo all chaos (service only, not data)
	@scripts/chaos.sh reset

smoke:           ## end-to-end test
	@scripts/smoke-test.sh

obs: prep        ## Week 6: also start Prometheus (:9090) and Grafana (:3000)
	docker compose --profile obs up -d --build
