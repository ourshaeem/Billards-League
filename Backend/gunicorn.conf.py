"""
Gunicorn settings for the production container.

Every value can be changed from the host's environment variables without
rebuilding the image. The defaults suit a small instance (512 MB - 1 GB):
two worker processes of four threads each. This app spends its time
waiting on MySQL, not computing, so threads serve the 2.5-second polling
of every open screen more cheaply than extra processes would.
"""
import logging
import os
import subprocess
import sys

# Render and Railway tell the app which port to listen on through PORT.
# The image sets 5000 for anywhere that doesn't.
bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"

workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
worker_class = "gthread"
threads = int(os.environ.get("GUNICORN_THREADS", "4"))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "30"))
graceful_timeout = 20

# Requests, errors and the app's own log lines all go to stdout/stderr,
# which is where Render and Railway collect logs.
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")

# Each worker imports the app itself, so no worker starts with a copy of
# another process's database connections.
preload_app = False

# The workers' heartbeat file. On a disk-backed filesystem, writing it can
# stall a worker - gunicorn's documented fix for Docker is shared memory.
worker_tmp_dir = "/dev/shm" if os.path.isdir("/dev/shm") else None

# gunicorn's runtime control socket isn't used here, and would otherwise
# be written into a home directory the container's user doesn't have.
control_socket_disable = True


def on_starting(server):
    """
    Runs once, before any worker exists: create or update the database
    with `flask prepare-db`. One start is one migration, however many
    workers there are. If the database can't be reached, gunicorn stops
    and the host's log says why.

    The command runs as a separate, fresh Python process, never inside
    this one. Every worker is a fork of this process and inherits its
    state, and a process that has already looked up the database's name
    and opened an encrypted connection doesn't fork safely: on a Mac the
    workers crashed (SIGSEGV) on their first query. Keeping this process
    away from the database altogether means there is nothing unsafe to
    inherit, on any system.
    """
    logging.basicConfig(
        level=getattr(logging, loglevel.upper(), logging.INFO),
        format="[%(levelname)s] %(name)s: %(message)s",
    )

    here = os.path.dirname(os.path.abspath(__file__))
    prepared = subprocess.run(
        [sys.executable, "-m", "flask", "--app", "app", "prepare-db"], cwd=here
    )
    if prepared.returncode != 0:
        raise RuntimeError("The database isn't ready (see the message above), so not starting.")
