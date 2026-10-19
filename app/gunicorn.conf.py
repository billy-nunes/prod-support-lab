# 2 worker processes x 4 threads = at most 8 requests in flight at once.
# That ceiling is small on purpose: slow dependencies and lock waits use it up fast.
bind = "0.0.0.0:8000"
workers = 2
worker_class = "gthread"
threads = 4
timeout = 30          # a worker stuck longer than this is killed and replaced
graceful_timeout = 10
accesslog = None      # the app writes its own key=value request log
errorlog = "-"
loglevel = "info"


def child_exit(server, worker):
    # Tidy up Prometheus multiprocess files for workers that died (normal exit, OOM kill, timeout).
    from prometheus_client import multiprocess
    multiprocess.mark_process_dead(worker.pid)
