from __future__ import annotations

import nest_asyncio
nest_asyncio.apply()  # Allow running asyncio in gunicorn/threading environments

import asyncio
import logging
import os
import sqlite3
import json
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime
from typing import Any, Dict, List, Optional

import ipaddress
import socket
from urllib.parse import urlparse as stdlib_urlparse

from flask import Flask, Response, jsonify, request, g, render_template
from qa_tool import qa_toolConfig, run_qa_tool
from config import settings

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION & LOGGING
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, settings.logging_level.upper(), logging.INFO),
    format="%(asctime)s - [%(levelname)s] - website_qa_api - %(message)s",
)
logger = logging.getLogger("website_qa_api")

# ─────────────────────────────────────────────────────────────────────────────
# DATABASE SCHEMA (DDL)
# ─────────────────────────────────────────────────────────────────────────────

# Schema focuses on capturing full data from qa_tool while providing
# indexed lookups for API performance.

_DDL_JOBS = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    request_id TEXT,
    url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    
    -- Config (stored for reference)
    max_pages INTEGER,
    max_depth INTEGER,
    run_ai INTEGER,
    
    -- Lifecycle
    submitted_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL,
    updated_at REAL NOT NULL,
    
    -- Summary results
    base_domain TEXT,
    master_qa_audit TEXT, -- JSON or Text
    total_internal_visited INTEGER DEFAULT 0,
    total_external_visited INTEGER DEFAULT 0,
    
    -- Errors
    error TEXT,
    total_tokens INTEGER DEFAULT 0
);
"""

_DDL_PAGES = """
CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    url TEXT NOT NULL,
    page_type TEXT NOT NULL, -- 'internal' or 'external'
    
    -- Basic URL report fields (promoted to columns for easy querying)
    http_status INTEGER,
    status_label TEXT,
    redirected INTEGER, -- 0/1
    final_url TEXT,
    load_time REAL,
    nav_time REAL,
    
    -- Complex data (stored as JSON)
    full_report TEXT, -- The entire 'report' dictionary from qa_tool
    
    FOREIGN KEY (job_id) REFERENCES jobs (id) ON DELETE CASCADE
);
"""

_DDL_INDEX = """
CREATE INDEX IF NOT EXISTS idx_pages_job_id ON pages(job_id);
"""

_DDL_FRONTIER = """
CREATE TABLE IF NOT EXISTS crawl_frontier (
    job_id TEXT NOT NULL,
    url TEXT NOT NULL,
    depth INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending', -- 'pending', 'processing', 'completed', 'failed'
    is_internal INTEGER NOT NULL, -- 0/1
    PRIMARY KEY (job_id, url),
    FOREIGN KEY (job_id) REFERENCES jobs (id) ON DELETE CASCADE
);
"""

# ─────────────────────────────────────────────────────────────────────────────
# JOB MANAGER
# ─────────────────────────────────────────────────────────────────────────────

class JobManager:
    """Thread-safe SQLite job store handling full persistence of crawl results."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript(_DDL_JOBS + _DDL_PAGES + _DDL_INDEX + _DDL_FRONTIER)

    def create_job(self, url: str, cfg: qa_toolConfig, request_id: str) -> str:
        job_id = str(uuid.uuid4())
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    id, request_id, url, status, submitted_at, updated_at,
                    max_pages, max_depth, run_ai
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id, request_id, url, 'pending', now, now,
                    cfg.max_pages, cfg.max_depth, int(cfg.run_ai)
                )
            )
        return job_id

    def mark_running(self, job_id: str):
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status='running', started_at=?, updated_at=? WHERE id=?",
                (now, now, job_id)
            )

    def add_tokens(self, job_id: str, tokens: int):
        """Atomically increment token count for a job."""
        if tokens <= 0:
            return
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET total_tokens = COALESCE(total_tokens, 0) + ? WHERE id=?",
                (tokens, job_id)
            )

    def mark_failed(self, job_id: str, error_msg: str):
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status='failed', finished_at=?, updated_at=?, error=? WHERE id=?",
                (now, now, error_msg, job_id)
            )
        _sse_publish(job_id, {"event": "job_done", "status": "failed", "error": error_msg})

    def mark_success(self, job_id: str, results: Any):
        """Finalizes the job status and master report."""
        now = time.time()
        res_dict = results if isinstance(results, dict) else asdict(results)
        
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE jobs SET 
                    status='success', 
                    finished_at=?, 
                    updated_at=?, 
                    base_domain=?, 
                    master_qa_audit=?, 
                    total_internal_visited=?, 
                    total_external_visited=? 
                WHERE id=?
                """,
                (
                    now, now, 
                    res_dict.get('base_domain'),
                    json.dumps(res_dict.get('master_qa_audit')) if not isinstance(res_dict.get('master_qa_audit'), str) else res_dict.get('master_qa_audit'),
                    res_dict.get('total_internal_pages_visited', 0),
                    res_dict.get('total_external_pages_visited', 0),
                    job_id
                )
            )
            conn.execute("DELETE FROM crawl_frontier WHERE job_id=?", (job_id,))
        _sse_publish(job_id, {"event": "job_done", "status": "success"})

    def add_to_frontier(self, job_id: str, urls_with_depth: List[tuple[str, int, bool]]):
        """Adds a batch of URLs to the persistent frontier."""
        with self._connect() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO crawl_frontier (job_id, url, depth, is_internal) VALUES (?, ?, ?, ?)",
                [(job_id, url, depth, 1 if internal else 0) for url, depth, internal in urls_with_depth]
            )

    def get_next_queued_url(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Atomically gets the next pending URL and marks it as processing."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT url, depth, is_internal FROM crawl_frontier WHERE job_id=? AND status='pending' LIMIT 1",
                (job_id,)
            ).fetchone()
            
            if row:
                data = dict(row)
                conn.execute(
                    "UPDATE crawl_frontier SET status='processing' WHERE job_id=? AND url=?",
                    (job_id, data['url'])
                )
                return data
            return None

    def mark_frontier_completed(self, job_id: str, url: str):
        with self._connect() as conn:
            conn.execute(
                "UPDATE crawl_frontier SET status='completed' WHERE job_id=? AND url=?",
                (job_id, url)
            )

    def mark_frontier_failed(self, job_id: str, url: str):
        with self._connect() as conn:
            conn.execute(
                "UPDATE crawl_frontier SET status='failed' WHERE job_id=? AND url=?",
                (job_id, url)
            )

    def get_crawl_stats(self, job_id: str) -> Dict[str, int]:
        with self._connect() as conn:
            internal = conn.execute(
                "SELECT COUNT(*) FROM crawl_frontier WHERE job_id=? AND is_internal=1 AND status='completed'",
                (job_id,)
            ).fetchone()[0]
            external = conn.execute(
                "SELECT COUNT(*) FROM crawl_frontier WHERE job_id=? AND is_internal=0 AND status='completed'",
                (job_id,)
            ).fetchone()[0]
            discovered = conn.execute(
                "SELECT COUNT(*) FROM crawl_frontier WHERE job_id=?",
                (job_id,)
            ).fetchone()[0]
            return {
                "internal_count": internal,
                "external_count": external,
                "discovered_count": discovered
            }

    def save_page_report(self, job_id: str, page_type: str, report: Dict[str, Any]):
        """Persists a single page report immediately."""
        with self._connect() as conn:
            self._insert_page(conn, job_id, page_type, report)
        _sse_publish(job_id, {
            "event": "page_completed",
            "url": report.get("url"),
            "page_type": page_type,
            "http_status": (report.get("url_report") or {}).get("http_status"),
        })

    def _insert_page(self, conn: sqlite3.Connection, job_id: str, page_type: str, report: Dict[str, Any]):
        url_report = report.get('url_report') or {}
        perf = url_report.get('performance') or {}
        
        conn.execute(
            """
            INSERT INTO pages (
                job_id, url, page_type, http_status, status_label, 
                redirected, final_url, load_time, nav_time, full_report
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id, 
                report.get('url'), 
                page_type,
                url_report.get('http_status'),
                url_report.get('status_label'),
                1 if url_report.get('redirected') else 0,
                url_report.get('final_url'),
                perf.get('total_load_seconds'),
                perf.get('navigation_seconds'),
                json.dumps(report)
            )
        )

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                return None
            
            job = dict(row)
            
            # Fetch individual page reports if they exist (allows Master Audit to fetch during crawl)
            if True: # job['status'] in ('success', 'running'):
                internal = []
                external = []
                
                # Fetch only columns needed for the summary view
                # We fetch 'url', 'page_type', 'http_status', 'status_label', 'redirected', 'final_url', 'load_time', 'nav_time'
                # and we selectively parse portions of full_report if needed.
                # To save memory, we skip loading 'full_report' entirely for external pages.
                
                page_rows = conn.execute(
                    "SELECT url, page_type, http_status, status_label, redirected, final_url, load_time, nav_time, full_report FROM pages WHERE job_id=?", 
                    (job_id,)
                ).fetchall()
                
                for pr in page_rows:
                    p_dict = dict(pr)
                    
                    # Prepare basic url_report structure as expected by UI
                    url_report_sum = {
                        "http_status": p_dict['http_status'],
                        "status_label": p_dict['status_label'],
                        "redirected": bool(p_dict['redirected']),
                        "final_url": p_dict['final_url'],
                        "performance": {
                            "total_load_seconds": p_dict['load_time'],
                            "navigation_seconds": p_dict['nav_time']
                        }
                    }

                    if p_dict['page_type'] == 'internal':
                        # For internal pages, we also need agent_summary and console_logs from full_report
                        agent_summary = None
                        console_logs = []
                        if p_dict['full_report']:
                            try:
                                full_p = json.loads(p_dict['full_report'])
                                agent_summary = full_p.get("agent_summary")
                                console_logs = full_p.get("url_report", {}).get("console_logs", [])
                            except:
                                pass
                        
                        url_report_sum["console_logs"] = console_logs
                        
                        internal.append({
                            "url": p_dict['url'],
                            "url_report": url_report_sum,
                            "agent_summary": agent_summary
                        })
                    else:
                        # External pages are minimal
                        external.append({
                            "url": p_dict['url'],
                            "url_report": url_report_sum
                        })
                
                # Deserialise master audit
                audit = job.get('master_qa_audit')
                if audit:
                    try:
                        audit = json.loads(audit)
                    except:
                        pass
                
                job['result'] = {
                    "initial_url": job['url'],
                    "base_domain": job['base_domain'],
                    "master_qa_audit": audit,
                    "total_internal_pages_visited": job['total_internal_visited'],
                    "total_external_pages_visited": job['total_external_visited'],
                    "internal_reports": internal,
                    "external_reports": external
                }
            else:
                job['result'] = None
                
            return job

    def list_jobs(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY submitted_at DESC LIMIT ? OFFSET ?",
                (limit, offset)
            ).fetchall()
            return [dict(r) for r in rows]

job_manager = JobManager(settings.api.db_path)


# ─────────────────────────────────────────────────────────────────────────────
# SSRF PROTECTION
# ─────────────────────────────────────────────────────────────────────────────

def _validate_url(url: str) -> Optional[str]:
    """Return an error message if the URL is unsafe, or None if OK."""
    try:
        parsed = stdlib_urlparse(url)
    except Exception:
        return "Malformed URL."

    if parsed.scheme not in ("http", "https"):
        return f"Unsupported scheme: {parsed.scheme}. Only http/https allowed."

    hostname = parsed.hostname
    if not hostname:
        return "URL has no hostname."

    blocked_hosts = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
    if hostname.lower() in blocked_hosts:
        return "Localhost URLs are not allowed."

    try:
        resolved = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for family, _, _, _, addr in resolved:
            ip = ipaddress.ip_address(addr[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return f"URL resolves to a private/reserved IP ({ip}). Not allowed."
    except socket.gaierror:
        pass  # DNS failure is fine — browser will report it during crawl

    return None


# ─────────────────────────────────────────────────────────────────────────────
# SSE EVENT BUS
# ─────────────────────────────────────────────────────────────────────────────

import queue as _queue

_sse_subscribers: Dict[str, List[_queue.Queue]] = {}
_sse_lock = threading.Lock()


def _sse_publish(job_id: str, event_data: Dict[str, Any]):
    """Push a JSON event to all SSE subscribers for this job."""
    with _sse_lock:
        subs = _sse_subscribers.get(job_id, [])
        for q in subs:
            try:
                q.put_nowait(event_data)
            except _queue.Full:
                pass


def _sse_subscribe(job_id: str) -> _queue.Queue:
    q: _queue.Queue = _queue.Queue(maxsize=100)
    with _sse_lock:
        _sse_subscribers.setdefault(job_id, []).append(q)
    return q


def _sse_unsubscribe(job_id: str, q: _queue.Queue):
    with _sse_lock:
        subs = _sse_subscribers.get(job_id, [])
        if q in subs:
            subs.remove(q)
        if not subs:
            _sse_subscribers.pop(job_id, None)


# ─────────────────────────────────────────────────────────────────────────────
# CANCELLATION REGISTRY
# ─────────────────────────────────────────────────────────────────────────────

_cancel_events: Dict[str, threading.Event] = {}
_cancel_lock = threading.Lock()


def _register_cancel_event(job_id: str) -> threading.Event:
    evt = threading.Event()
    with _cancel_lock:
        _cancel_events[job_id] = evt
    return evt


def _unregister_cancel_event(job_id: str):
    with _cancel_lock:
        _cancel_events.pop(job_id, None)


def cancel_job(job_id: str) -> bool:
    """Signal a running job to stop. Returns True if the job was found and signalled."""
    with _cancel_lock:
        evt = _cancel_events.get(job_id)
    if evt:
        evt.set()
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# BACKGROUND WORKER
# ─────────────────────────────────────────────────────────────────────────────

def _run_qa_background(job_id: str, cfg: qa_toolConfig, timeout: int):
    cancel_event = _register_cancel_event(job_id)
    try:
        logger.info(f"Background job {job_id} started.")
        job_manager.mark_running(job_id)
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        if timeout > 0:
            result = loop.run_until_complete(asyncio.wait_for(
                run_qa_tool(cfg, sink=job_manager, job_id=job_id, cancel_event=cancel_event),
                timeout=timeout,
            ))
        else:
            result = loop.run_until_complete(
                run_qa_tool(cfg, sink=job_manager, job_id=job_id, cancel_event=cancel_event)
            )

        if cancel_event.is_set():
            job_manager.mark_failed(job_id, "Cancelled by user.")
            logger.info(f"Background job {job_id} cancelled.")
        else:
            job_manager.mark_success(job_id, result)
            logger.info(f"Background job {job_id} completed successfully.")
    except asyncio.TimeoutError:
        job_manager.mark_failed(job_id, f"Timeout after {timeout} seconds.")
        logger.warning(f"Background job {job_id} timed out.")
    except Exception as e:
        logger.exception(f"Background job {job_id} failed: {e}")
        job_manager.mark_failed(job_id, str(e))
    finally:
        loop.close()
        _unregister_cancel_event(job_id)

# ─────────────────────────────────────────────────────────────────────────────
# FLASK APPLICATION & ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = settings.api.max_body_bytes
    app.json.sort_keys = False

    @app.before_request
    def _ensure_request_id():
        g.request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

    @app.after_request
    def _add_headers(response):
        response.headers["X-Request-ID"] = g.get("request_id", "")
        response.headers["Cache-Control"] = "no-store"
        return response

    # ERROR HANDLERS

    @app.errorhandler(404)
    def _handle_404(e):
        if request.path.startswith("/api/"):
            return jsonify({
                "ok": False,
                "error": {"code": "not_found", "message": "Resource not found."},
                "request_id": g.get("request_id")
            }), 404
        return render_template("dashboard.html"), 200 # SPA fallback

    @app.errorhandler(Exception)
    def _handle_unexpected(e):
        logger.exception("Internal error: %s", e)
        if request.path.startswith("/api/"):
            return jsonify({
                "ok": False,
                "error": {"code": "internal_error", "message": "An unexpected error occurred."},
                "request_id": g.get("request_id")
            }), 500
        return "Internal Server Error", 500

    # API ENDPOINTS

    @app.route("/api/run-qa", methods=["POST"])
    def run_qa():
        if not request.is_json:
            return jsonify({"ok": False, "error": {"code": "invalid_json", "message": "JSON body required."}}), 400
        
        data = request.json
        url = data.get("url")
        if not url:
            return jsonify({"ok": False, "error": {"code": "missing_url", "message": "Target URL is required."}}), 400

        url_error = _validate_url(url)
        if url_error:
            return jsonify({"ok": False, "error": {"code": "invalid_url", "message": url_error}}), 400

        # Build Config
        cfg = qa_toolConfig(
            initial_url=url,
            max_pages=data.get("max_pages"),
            max_depth=data.get("max_depth"),
            run_ai=data.get("run_ai", True),
            headless=True
        )
        
        timeout = int(data.get("timeout_seconds") or 0)
        job_id = job_manager.create_job(url, cfg, g.request_id)
        
        # Start background thread
        thread = threading.Thread(target=_run_qa_background, args=(job_id, cfg, timeout), daemon=True)
        thread.start()
        
        return jsonify({
            "ok": True,
            "job_id": job_id,
            "status": "pending",
            "message": "QA job enqueued successfully.",
            "request_id": g.request_id
        }), 202

    @app.route("/api/status/<job_id>", methods=["GET", "POST"])
    def get_status(job_id: str):
        job = job_manager.get_job(job_id)
        if not job:
            return jsonify({"ok": False, "error": {"code": "not_found", "message": "Job not found."}}), 404
        
        # We can filter result here if we want a smaller payload
        return jsonify({
            "ok": True,
            "job_id": job["id"],
            "status": job["status"],
            "url": job["url"],
            "submitted_at": job["submitted_at"],
            "started_at": job.get("started_at"),
            "finished_at": job.get("finished_at"),
            "error": job.get("error"),
            "total_tokens": job.get("total_tokens", 0),
            "result": job.get("result")
        }), 200

    @app.route("/api/jobs", methods=["GET"])
    def list_jobs():
        try:
            limit = int(request.args.get("limit", 50))
            offset = int(request.args.get("offset", 0))
        except:
            limit, offset = 50, 0
        
        jobs = job_manager.list_jobs(limit, offset)
        return jsonify({
            "ok": True,
            "jobs": jobs,
            "limit": limit,
            "offset": offset
        }), 200

    @app.route("/api/jobs/<job_id>/stream", methods=["GET"])
    def stream_job(job_id: str):
        job = job_manager.get_job(job_id)
        if not job:
            return jsonify({"ok": False, "error": {"code": "not_found", "message": "Job not found."}}), 404

        q = _sse_subscribe(job_id)

        def generate():
            try:
                while True:
                    try:
                        event = q.get(timeout=30)
                        yield f"data: {json.dumps(event)}\n\n"
                        if event.get("event") == "job_done":
                            break
                    except _queue.Empty:
                        yield ": heartbeat\n\n"
            finally:
                _sse_unsubscribe(job_id, q)

        return Response(generate(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.route("/api/jobs/<job_id>/cancel", methods=["POST"])
    def cancel_job_endpoint(job_id: str):
        job = job_manager.get_job(job_id)
        if not job:
            return jsonify({"ok": False, "error": {"code": "not_found", "message": "Job not found."}}), 404
        if job["status"] not in ("pending", "running"):
            return jsonify({"ok": False, "error": {"code": "invalid_state", "message": f"Job is already {job['status']}."}}), 409
        signalled = cancel_job(job_id)
        if not signalled:
            job_manager.mark_failed(job_id, "Cancelled by user.")
        return jsonify({"ok": True, "message": "Cancellation requested.", "job_id": job_id}), 200

    @app.route("/", methods=["GET"])
    def index():
        return render_template("dashboard.html")

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"ok": True, "status": "up"}), 200

    return app

app = create_app()

if __name__ == "__main__":
    host = os.getenv("HOST", settings.api.host)
    port = int(os.getenv("PORT", str(settings.api.port)))
    app.run(host=host, port=port)
