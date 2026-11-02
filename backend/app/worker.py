"""PostgreSQL-backed worker.

Jobs are claimed with SKIP LOCKED on PostgreSQL. A leased job heartbeats so a
crash returns it to the queue when the lease expires. Ambiguous YouCam
submissions are not resubmitted by that recovery.
"""

from __future__ import annotations

import os
import socket
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.config import get_settings
from app.db import session_factory
from app.errors import AppError
from app.models import Experiment, Job, WorkerHeartbeat, utcnow
from app.queue import claim_job, finish_job, heartbeat_job
from app.quotas import release_units
from app.runner import advance_experiment, advance_recapture
from app.services import purge_expired
from app.storage import build_storage
from app.variant_release import release_pending
from app.youcam import YouCamClient


def safe_error(exc: BaseException) -> str:
    text = "".join(traceback.format_exception_only(type(exc), exc)).strip()
    redacted = []
    for token in text.split():
        if token.lower().startswith("http://") or token.lower().startswith("https://") or token.lower().startswith("bearer"):
            redacted.append("[redacted]")
        else:
            redacted.append(token)
    return " ".join(redacted)[:500]


def _worker_id(settings) -> str:
    return settings.worker_id or f"{socket.gethostname()}-{os.getpid()}"


def _serve_health(port: int) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/health"):
                body = b'{"status":"ok","service":"shade-of-doubt-worker"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, fmt: str, *args) -> None:
            return

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    server.serve_forever()


def _beat(job_id: str, worker_id: str, stop: threading.Event) -> None:
    settings = get_settings()
    while not stop.wait(settings.worker_heartbeat_seconds):
        session = session_factory()()
        try:
            heartbeat_job(session, job_id, worker_id, settings)
            row = session.get(WorkerHeartbeat, worker_id)
            now = utcnow()
            if row is None:
                session.add(WorkerHeartbeat(worker_id=worker_id, last_seen=now, pid=os.getpid()))
            else:
                row.last_seen = now
            session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()


def _run_job(job: Job, worker_id: str) -> None:
    settings = get_settings()
    storage = build_storage(settings)
    stop = threading.Event()
    thread = threading.Thread(target=_beat, args=(job.id, worker_id, stop), daemon=True)
    thread.start()
    session = session_factory()()
    try:
        client = None
        try:
            if job.kind == "retention":
                purge_expired(session, storage, settings)
                session.commit()
                action, delay = "succeeded", 0
            elif job.kind == "experiment":
                client = YouCamClient(settings)
                action, delay = advance_experiment(session, storage, client, settings, job.payload_json["experiment_id"])
            elif job.kind == "recapture":
                client = YouCamClient(settings)
                action, delay = advance_recapture(session, storage, client, settings, job.payload_json["recapture_session_id"])
            else:
                action, delay = "failed", 0
        finally:
            if client is not None:
                client.close()
        current = session.get(Job, job.id)
        if current is not None:
            finish_job(session, current, "succeeded" if action == "done" else action, delay_seconds=delay)
            session.commit()
    except AppError as exc:
        session.rollback()
        _fail_configuration(job, exc)
    except Exception as exc:
        session.rollback()
        repair = session_factory()()
        try:
            current = repair.get(Job, job.id)
            if current is not None:
                finish_job(repair, current, "retry", error=safe_error(exc), delay_seconds=15)
                repair.commit()
        finally:
            repair.close()
    finally:
        stop.set()
        session.close()


def _fail_configuration(job: Job, exc: AppError) -> None:
    settings = get_settings()
    session = session_factory()()
    try:
        experiment_id = (job.payload_json or {}).get("experiment_id")
        if experiment_id:
            experiment = session.get(Experiment, experiment_id)
            if experiment is not None and experiment.status == "running":
                experiment.status = "failed"
                experiment.stage = "failed"
                experiment.error_code = exc.code
                experiment.error_message = exc.message
                release_pending(session, settings, experiment)
        current = session.get(Job, job.id)
        if current is not None:
            finish_job(session, current, "failed", error=exc.message)
        session.commit()
    finally:
        session.close()


def main() -> None:
    settings = get_settings()
    worker_id = _worker_id(settings)
    port = int(os.environ.get("PORT") or settings.worker_health_port)
    threading.Thread(target=_serve_health, args=(port,), daemon=True).start()
    last_purge = 0.0
    while True:
        session = session_factory()()
        try:
            now = utcnow()
            beat = session.get(WorkerHeartbeat, worker_id)
            if beat is None:
                session.add(WorkerHeartbeat(worker_id=worker_id, last_seen=now, pid=os.getpid()))
            else:
                beat.last_seen = now
                beat.pid = os.getpid()
            retention_waiting = session.query(Job).filter(Job.kind == "retention", Job.status.in_(["queued", "leased"])).count()
            if time.time() - last_purge > 3600 and retention_waiting == 0:
                session.add(
                    Job(
                        id=__import__("uuid").uuid4().__str__(),
                        owner_id="system",
                        experiment_id=None,
                        kind="retention",
                        status="queued",
                        payload_json={},
                        max_attempts=3,
                        run_after=now,
                    )
                )
                last_purge = time.time()
            job = claim_job(session, worker_id, settings)
            session.commit()
            claimed = None if job is None else job.id
        except Exception:
            session.rollback()
            claimed = None
            time.sleep(settings.worker_idle_seconds)
        finally:
            session.close()
        if not claimed:
            time.sleep(settings.worker_idle_seconds)
            continue
        follow = session_factory()()
        try:
            job = follow.get(Job, claimed)
            if job is not None:
                _run_job(job, worker_id)
        finally:
            follow.close()


if __name__ == "__main__":
    main()
