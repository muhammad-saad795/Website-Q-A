from __future__ import annotations

import nest_asyncio
nest_asyncio.apply()  # Allow asyncio.run() inside gunicorn gthread worker threads

import asyncio
import logging
import os
import socket
import uuid
from ipaddress import ip_address
from typing import Any, Dict, List, Optional
import time
from urllib.parse import urlparse
import json
import sqlite3
import threading
from flask import Flask, jsonify, request, g

from qa_tool import qa_toolConfig, run_qa_tool
from config import settings


logger = logging.getLogger("website_qa_api")
logging.basicConfig(
    level=settings.logging_level,
    format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
    datefmt="%H:%M:%S",
)


class ApiError(Exception):
    def __init__(self, message: str, status_code: int = 400, code: str = "bad_request") -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


def _is_valid_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def _is_private_or_local_host(host: str) -> bool:
    if not host:
        return True

    host_l = host.lower().strip()
    blocked_hosts = {"localhost", "0.0.0.0", "::1"}
    if host_l in blocked_hosts:
        return True

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False

    for info in infos:
        ip_raw = info[4][0]
        ip_obj = ip_address(ip_raw)
        if (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_multicast
            or ip_obj.is_reserved
            or ip_obj.is_unspecified
        ):
            return True

    return False


def _parse_optional_int(payload: Dict[str, Any], key: str, min_value: int, max_value: Optional[int] = None) -> Optional[int]:
    if key not in payload or payload[key] is None:
        return None

    value = payload[key]
    if not isinstance(value, int):
        raise ApiError(f"'{key}' must be an integer.", status_code=400, code="validation_error")
    if value < min_value:
        raise ApiError(f"'{key}' must be at least {min_value}.", status_code=400, code="validation_error")
    if max_value is not None and value > max_value:
        raise ApiError(
            f"'{key}' must be between {min_value} and {max_value}.",
            status_code=400,
            code="validation_error",
        )
    return value


def _parse_optional_bool(payload: Dict[str, Any], key: str, default: bool) -> bool:
    if key not in payload or payload[key] is None:
        return default

    value = payload[key]
    if not isinstance(value, bool):
        raise ApiError(f"'{key}' must be a boolean.", status_code=400, code="validation_error")
    return value


def _parse_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ApiError("Request body must be a JSON object.", status_code=400, code="validation_error")

    url = payload.get("url")
    if not isinstance(url, str) or not url.strip():
        raise ApiError("'url' is required and must be a non-empty string.", status_code=400, code="validation_error")
    url = url.strip()

    if not _is_valid_http_url(url):
        raise ApiError("'url' must be a valid http/https URL.", status_code=400, code="validation_error")

    parsed = urlparse(url)
    if _is_private_or_local_host(parsed.hostname or ""):
        raise ApiError(
            "Local/private network targets are not allowed.",
            status_code=400,
            code="blocked_target",
        )

    max_pages = _parse_optional_int(payload, "max_pages", min_value=1)
    max_depth = _parse_optional_int(payload, "max_depth", min_value=0)
    run_ai = _parse_optional_bool(payload, "run_ai", default=True)
    timeout_seconds = _parse_optional_int(payload, "timeout_seconds", min_value=0, max_value=86400)

    return {
        "url": url,
        "max_pages": max_pages,
        "max_depth": max_depth,
        "run_ai": run_ai,
        "timeout_seconds": timeout_seconds if timeout_seconds is not None else 0,
    }


# ---------------------------------------------------------------------------
# Production-grade Job Manager backed by SQLite
# ---------------------------------------------------------------------------
# Schema overview:
#
#   jobs          – one row per QA run, stores all job metadata + crawl summary
#   page_reports  – one row per crawled page, linked to jobs via job_id (FK)
#
# No result data is ever written to the filesystem; everything lives in the DB.
# ---------------------------------------------------------------------------

_JOBS_DDL = """
CREATE TABLE IF NOT EXISTS jobs (
    -- Identity
    id                      TEXT PRIMARY KEY,
    request_id              TEXT,

    -- Lifecycle
    status                  TEXT NOT NULL DEFAULT 'pending',
    submitted_at            REAL NOT NULL,
    started_at              REAL,
    finished_at             REAL,
    updated_at              REAL NOT NULL,

    -- Request parameters (denormalised for quick inspection)
    url                     TEXT NOT NULL,
    max_pages               INTEGER,
    max_depth               INTEGER,
    run_ai                  INTEGER NOT NULL DEFAULT 1,   -- BOOLEAN (0/1)
    timeout_seconds         INTEGER NOT NULL DEFAULT 0,

    -- Crawl-level results (populated on success)
    base_domain             TEXT,
    master_qa_audit         TEXT,
    total_internal_pages    INTEGER,
    total_external_pages    INTEGER,

    -- Failure info
    error                   TEXT
);
"""

_PAGE_REPORTS_DDL = """
CREATE TABLE IF NOT EXISTS page_reports (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id                  TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,

    -- Classification
    page_type               TEXT NOT NULL CHECK(page_type IN ('internal', 'external')),
    url                     TEXT NOT NULL,

    -- URL health (from url_report)
    http_status             INTEGER,
    status_label            TEXT,
    redirect_detected       INTEGER,   -- BOOLEAN (0/1)
    load_time_seconds       REAL,
    navigation_time_seconds REAL,

    -- Structured sub-reports stored as JSON text
    console_errors          TEXT,      -- JSON array
    layout_report           TEXT,      -- JSON object

    -- AI output
    agent_summary           TEXT,

    -- Per-page error (if analysis itself failed)
    error                   TEXT
);
"""

_PAGE_REPORTS_IDX = """
CREATE INDEX IF NOT EXISTS idx_page_reports_job_id ON page_reports(job_id);
"""


class JobManager:
    """Thread-safe SQLite-backed job store.

    All QA results are persisted to the database; no files are written to disk.
    Each connection is created per-call so that multiple threads can safely
    read/write without sharing a single connection object.
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        # Ensure the parent directory exists (important for Railway volume paths like /data/jobs.db)
        from pathlib import Path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL;")   # concurrent readers + one writer
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_JOBS_DDL + _PAGE_REPORTS_DDL + _PAGE_REPORTS_IDX)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_job(
        self,
        url: str,
        max_pages: Optional[int],
        max_depth: Optional[int],
        run_ai: bool,
        timeout_seconds: int,
        request_id: Optional[str] = None,
    ) -> str:
        """Insert a new job row and return the generated job_id."""
        job_id = str(uuid.uuid4())
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs
                    (id, request_id, status, submitted_at, updated_at,
                     url, max_pages, max_depth, run_ai, timeout_seconds)
                VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?)
                """,
                (job_id, request_id, now, now,
                 url, max_pages, max_depth, int(run_ai), timeout_seconds),
            )
        return job_id

    def mark_running(self, job_id: str) -> None:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status='running', started_at=?, updated_at=? WHERE id=?",
                (now, now, job_id),
            )

    def mark_success(self, job_id: str, crawl_result: Dict[str, Any]) -> None:
        """Persist the full crawl result into normalised DB columns."""
        now = time.time()

        internal_reports: List[Dict[str, Any]] = crawl_result.get("internal_reports", [])
        external_reports: List[Dict[str, Any]] = crawl_result.get("external_reports", [])

        with self._connect() as conn:
            # Update the jobs row with crawl-level summary
            conn.execute(
                """
                UPDATE jobs SET
                    status               = 'success',
                    finished_at          = ?,
                    updated_at           = ?,
                    base_domain          = ?,
                    master_qa_audit      = ?,
                    total_internal_pages = ?,
                    total_external_pages = ?
                WHERE id = ?
                """,
                (
                    now, now,
                    crawl_result.get("base_domain"),
                    crawl_result.get("master_qa_audit"),
                    crawl_result.get("total_internal_pages_visited", len(internal_reports)),
                    len(external_reports),
                    job_id,
                ),
            )

            # Insert one row per internal page
            for report in internal_reports:
                self._insert_page_report(conn, job_id, "internal", report)

            # Insert one row per external page
            for report in external_reports:
                self._insert_page_report(conn, job_id, "external", report)

    def mark_failed(self, job_id: str, error: str) -> None:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status='failed', finished_at=?, updated_at=?, error=? WHERE id=?",
                (now, now, error, job_id),
            )

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Return the full job record including all page reports."""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM jobs WHERE id = ?", (job_id,)
                ).fetchone()

                if not row:
                    return None

                job = dict(row)
                job["run_ai"] = bool(job["run_ai"])

                # Attach page reports only when the job has finished
                if job["status"] == "success":
                    page_rows = conn.execute(
                        "SELECT * FROM page_reports WHERE job_id = ? ORDER BY id",
                        (job_id,),
                    ).fetchall()

                    internal_reports = []
                    external_reports = []
                    for pr in page_rows:
                        pr_dict = self._deserialise_page_report(dict(pr))
                        if pr_dict["page_type"] == "internal":
                            internal_reports.append(pr_dict)
                        else:
                            external_reports.append(pr_dict)

                    job["result"] = {
                        "initial_url": job["url"],
                        "base_domain": job["base_domain"],
                        "master_qa_audit": job["master_qa_audit"],
                        "total_internal_pages_visited": job["total_internal_pages"],
                        "total_external_pages_visited": job["total_external_pages"],
                        "internal_reports": internal_reports,
                        "external_reports": external_reports,
                    }
                else:
                    job["result"] = None

                return job

        except Exception as exc:
            logger.error("Failed to fetch job %s from DB: %s", job_id, exc)
            return None

    def list_jobs(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """Return a lightweight list of jobs (no page reports)."""
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT id, status, url, submitted_at, finished_at,
                           total_internal_pages, total_external_pages, error
                    FROM jobs
                    ORDER BY submitted_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (limit, offset),
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception as exc:
            logger.error("Failed to list jobs: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _insert_page_report(
        conn: sqlite3.Connection,
        job_id: str,
        page_type: str,
        report: Dict[str, Any],
    ) -> None:
        url_report: Dict[str, Any] = report.get("url_report") or {}
        layout_report = report.get("layout_report")
        console_errors = url_report.get("console_errors") or []

        conn.execute(
            """
            INSERT INTO page_reports
                (job_id, page_type, url,
                 http_status, status_label, redirect_detected,
                 load_time_seconds, navigation_time_seconds,
                 console_errors, layout_report,
                 agent_summary, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                page_type,
                report.get("url"),
                url_report.get("http_status"),
                url_report.get("status_label"),
                int(bool(url_report.get("redirect_detected"))),
                url_report.get("load_time_seconds"),
                url_report.get("navigation_time_seconds"),
                json.dumps(console_errors) if console_errors else None,
                json.dumps(layout_report) if layout_report is not None else None,
                report.get("agent_summary"),
                report.get("error"),
            ),
        )

    @staticmethod
    def _deserialise_page_report(row: Dict[str, Any]) -> Dict[str, Any]:
        """Convert raw DB row back to the API-facing dict shape."""
        row["redirect_detected"] = bool(row.get("redirect_detected"))
        for json_col in ("console_errors", "layout_report"):
            raw = row.get(json_col)
            row[json_col] = json.loads(raw) if raw else None
        # Remove internal FK column from output
        row.pop("job_id", None)
        return row


job_manager = JobManager(settings.api.db_path)


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

def _run_qa_background(job_id: str, cfg: qa_toolConfig, timeout: int) -> None:
    """Worker function executed in a daemon thread per QA job."""
    try:
        logger.info("Background QA started [job_id=%s]", job_id)
        job_manager.mark_running(job_id)

        if timeout > 0:
            result = asyncio.run(asyncio.wait_for(run_qa_tool(cfg), timeout=timeout))
        else:
            result = asyncio.run(run_qa_tool(cfg))

        job_manager.mark_success(job_id, result)
        logger.info("Background QA succeeded [job_id=%s]", job_id)

    except asyncio.TimeoutError:
        msg = f"QA run exceeded timeout ({timeout}s)."
        job_manager.mark_failed(job_id, msg)
        logger.warning("Background QA timed out [job_id=%s]", job_id)

    except Exception as err:
        logger.exception("Background QA failed [job_id=%s]: %s", job_id, err)
        job_manager.mark_failed(job_id, str(err))


# ---------------------------------------------------------------------------
# Flask application
# ---------------------------------------------------------------------------

def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = settings.api.max_body_bytes
    app.json.sort_keys = False

    @app.before_request
    def _attach_request_id() -> None:
        g.request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

    @app.after_request
    def _add_response_headers(response):  # type: ignore[no-untyped-def]
        response.headers["X-Request-ID"] = g.get("request_id", "")
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(ApiError)
    def _handle_api_error(err: ApiError):  # type: ignore[no-untyped-def]
        return (
            jsonify({"ok": False, "error": {"code": err.code, "message": err.message}, "request_id": g.get("request_id")}),
            err.status_code,
        )

    @app.errorhandler(413)
    def _handle_too_large(_err):  # type: ignore[no-untyped-def]
        return (
            jsonify({"ok": False, "error": {"code": "payload_too_large", "message": "Request body is too large."}, "request_id": g.get("request_id")}),
            413,
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(err: Exception):  # type: ignore[no-untyped-def]
        logger.exception("Unhandled API error [request_id=%s]: %s", g.get("request_id"), err)
        return (
            jsonify({"ok": False, "error": {"code": "internal_error", "message": "Internal server error."}, "request_id": g.get("request_id")}),
            500,
        )

    # ------------------------------------------------------------------
    # Endpoints
    # ------------------------------------------------------------------

    @app.post("/api/run-qa")
    def run_qa_endpoint():  # type: ignore[no-untyped-def]
        """Enqueue a new QA crawl job. Returns 202 with job_id immediately."""
        if not request.is_json:
            raise ApiError("Content-Type must be application/json.", status_code=415, code="unsupported_media_type")

        payload = request.get_json(silent=True)
        if payload is None:
            raise ApiError("Malformed JSON body.", status_code=400, code="validation_error")

        parsed = _parse_payload(payload)

        cfg = qa_toolConfig(
            initial_url=parsed["url"],
            max_pages=parsed["max_pages"],
            max_depth=parsed["max_depth"],
            run_ai=parsed["run_ai"],
            interactive=False,
            output_file=None,
        )

        job_id = job_manager.create_job(
            url=parsed["url"],
            max_pages=parsed["max_pages"],
            max_depth=parsed["max_depth"],
            run_ai=parsed["run_ai"],
            timeout_seconds=parsed["timeout_seconds"],
            request_id=g.get("request_id"),
        )

        logger.info(
            "Enqueued QA run [job_id=%s, request_id=%s, url=%s]",
            job_id, g.get("request_id"), parsed["url"],
        )

        thread = threading.Thread(
            target=_run_qa_background,
            args=(job_id, cfg, parsed["timeout_seconds"]),
            daemon=True,
        )
        thread.start()

        return (
            jsonify({
                "ok": True,
                "job_id": job_id,
                "request_id": g.get("request_id"),
                "status": "pending",
                "message": "QA run enqueued successfully.",
            }),
            202,
        )

    @app.get("/api/status/<job_id>")
    def get_status_endpoint(job_id: str):  # type: ignore[no-untyped-def]
        """Poll the status (and result) of a previously submitted job."""
        job = job_manager.get_job(job_id)
        if not job:
            raise ApiError("Job not found.", status_code=404, code="not_found")

        return jsonify({
            "ok": True,
            "job_id": job["id"],
            "status": job["status"],
            "url": job["url"],
            "submitted_at": job["submitted_at"],
            "started_at": job.get("started_at"),
            "finished_at": job.get("finished_at"),
            "error": job.get("error"),
            "result": job.get("result"),
        }), 200

    @app.get("/api/jobs")
    def list_jobs_endpoint():  # type: ignore[no-untyped-def]
        """Return a paginated list of all jobs (lightweight, no page reports)."""
        try:
            limit = min(int(request.args.get("limit", 50)), 200)
            offset = max(int(request.args.get("offset", 0)), 0)
        except ValueError:
            raise ApiError("'limit' and 'offset' must be integers.", status_code=400, code="validation_error")

        jobs = job_manager.list_jobs(limit=limit, offset=offset)
        return jsonify({"ok": True, "jobs": jobs, "limit": limit, "offset": offset}), 200

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host=os.getenv("HOST", settings.api.host),
        port=int(os.getenv("PORT", str(settings.api.port))),
    )
