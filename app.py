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

from flask import Flask, jsonify, request, g
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
    error TEXT
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
            conn.executescript(_DDL_JOBS + _DDL_PAGES + _DDL_INDEX)

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

    def mark_failed(self, job_id: str, error_msg: str):
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status='failed', finished_at=?, updated_at=?, error=? WHERE id=?",
                (now, now, error_msg, job_id)
            )

    def mark_success(self, job_id: str, results: Any):
        """Stores the full results into the database."""
        now = time.time()
        
        # results is a CrawlResult object (or asdict'd mapping)
        res_dict = results if isinstance(results, dict) else asdict(results)
        
        with self._connect() as conn:
            # 1. Update overall job
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
                    len(res_dict.get('external_reports', [])),
                    job_id
                )
            )
            
            # 2. Insert internal pages
            for report in res_dict.get('internal_reports', []):
                self._insert_page(conn, job_id, 'internal', report)
            
            # 3. Insert external pages
            for report in res_dict.get('external_reports', []):
                self._insert_page(conn, job_id, 'external', report)

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
            
            # If success, fetch individual page reports
            if job['status'] == 'success':
                internal = []
                external = []
                page_rows = conn.execute("SELECT * FROM pages WHERE job_id=?", (job_id,)).fetchall()
                for pr in page_rows:
                    p_dict = dict(pr)
                    # For the API, we can decide what to expose.
                    # By default, we'll expose the deserialised full_report if requested,
                    # or a summarized version.
                    full_p = json.loads(p_dict['full_report']) if p_dict['full_report'] else {}
                    
                    if p_dict['page_type'] == 'internal':
                        # Internal: url, url_report, agent_summary
                        internal.append({
                            "url": full_p.get("url"),
                            "url_report": full_p.get("url_report"),
                            "agent_summary": full_p.get("agent_summary")
                        })
                    else:
                        # External: url, url_report
                        external.append({
                            "url": full_p.get("url"),
                            "url_report": full_p.get("url_report")
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
# BACKGROUND WORKER
# ─────────────────────────────────────────────────────────────────────────────

def _run_qa_background(job_id: str, cfg: qa_toolConfig, timeout: int):
    try:
        logger.info(f"Background job {job_id} started.")
        job_manager.mark_running(job_id)
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        if timeout > 0:
            result = loop.run_until_complete(asyncio.wait_for(run_qa_tool(cfg), timeout=timeout))
        else:
            result = loop.run_until_complete(run_qa_tool(cfg))
            
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
        return jsonify({
            "ok": False,
            "error": {"code": "not_found", "message": "Resource not found."},
            "request_id": g.get("request_id")
        }), 404

    @app.errorhandler(405)
    def _handle_405(e):
        return jsonify({
            "ok": False,
            "error": {"code": "method_not_allowed", "message": f"Method {request.method} not allowed."},
            "request_id": g.get("request_id")
        }), 405

    @app.errorhandler(413)
    def _handle_too_large(e):
        return jsonify({
            "ok": False,
            "error": {"code": "payload_too_large", "message": "Request body exceeds maximum size."},
            "request_id": g.get("request_id")
        }), 413

    @app.errorhandler(Exception)
    def _handle_unexpected(e):
        logger.exception("Internal error: %s", e)
        return jsonify({
            "ok": False,
            "error": {"code": "internal_error", "message": "An unexpected error occurred."},
            "request_id": g.get("request_id")
        }), 500

    # API ENDPOINTS

    @app.route("/api/run-qa", methods=["POST"])
    def run_qa():
        if not request.is_json:
            return jsonify({"ok": False, "error": {"code": "invalid_json", "message": "JSON body required."}}), 400
        
        data = request.json
        url = data.get("url")
        if not url:
            return jsonify({"ok": False, "error": {"code": "missing_url", "message": "Target URL is required."}}), 400

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

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"ok": True, "status": "up"}), 200

    return app

app = create_app()

if __name__ == "__main__":
    host = os.getenv("HOST", settings.api.host)
    port = int(os.getenv("PORT", str(settings.api.port)))
    app.run(host=host, port=port)
