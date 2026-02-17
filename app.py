from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid
from ipaddress import ip_address
from typing import Any, Dict, Optional
import time
from dataclasses import asdict
from urllib.parse import urlparse
import json

from pathlib import Path
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


import threading

RESULTS_DIR = Path(settings.api.results_dir)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# Job Manager
class JobManager:
    def __init__(self) -> None:
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create_job(self, config: qa_toolConfig, request_id: Optional[str] = None) -> str:
        job_id = str(uuid.uuid4())
        job_data = {
            "id": job_id,
            "status": "pending",
            "submitted_at": time.time(),
            "config": asdict(config),
            "request_id": request_id,
            "result": None,
            "error": None
        }
        with self._lock:
            self._jobs[job_id] = job_data
        return job_id

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            # If job is in memory, return a copy
            if job_id in self._jobs:
                job = self._jobs[job_id].copy()
            else:
                job = None
            
        # If result is missing in memory (e.g. after server restart or saved to disk)
        if job is None or (job["status"] == "success" and job.get("result") is None):
            result_path = RESULTS_DIR / f"{job_id}.json"
            if result_path.exists():
                try:
                    with open(result_path, "r", encoding="utf-8") as f:
                        result_data = json.load(f)
                    
                    if job is None:
                        # Reconstruct basic job metadata from disk if it was lost from memory
                        job = {
                            "id": job_id,
                            "status": "success",
                            "submitted_at": None,
                            "finished_at": result_path.stat().st_mtime,
                            "config": {"initial_url": result_data.get("initial_url")},
                            "result": result_data,
                            "error": None
                        }
                        # Add back to memory for faster future access
                        with self._lock:
                            self._jobs[job_id] = job
                    else:
                        # Just update the result field for the existing memory entry
                        job["result"] = result_data
                except Exception as e:
                    logger.error(f"Failed to load result from disk for job {job_id}: {e}")
        return job

    def update_job(self, job_id: str, updates: Dict[str, Any]) -> None:
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].update(updates)
                self._jobs[job_id]["updated_at"] = time.time()

job_manager = JobManager()


def _run_qa_background(job_id: str, cfg: qa_toolConfig, timeout: int) -> None:
    """Worker function to run the QA tool in a separate thread."""
    try:
        logger.info("Background QA process started [job_id=%s]", job_id)
        job_manager.update_job(job_id, {"status": "running"})
        
        if timeout > 0:
            result = asyncio.run(asyncio.wait_for(run_qa_tool(cfg), timeout=timeout))
        else:
            result = asyncio.run(run_qa_tool(cfg))
        
        import json
        result_path = RESULTS_DIR / f"{job_id}.json"
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

        job_manager.update_job(job_id, {
            "status": "success",
            "result": None,  # Keep memory clear, load from disk on request
            "finished_at": time.time()
        })
        logger.info("Background QA process succeeded [job_id=%s], result saved to disk", job_id)
        
    except asyncio.TimeoutError:
        job_manager.update_job(job_id, {
            "status": "failed",
            "error": f"QA run exceeded timeout ({timeout}s).",
            "finished_at": time.time()
        })
        logger.warning("Background QA process timed out [job_id=%s]", job_id)
    except Exception as err:
        logger.exception("Background QA process failed [job_id=%s]: %s", job_id, err)
        job_manager.update_job(job_id, {
            "status": "failed",
            "error": str(err),
            "finished_at": time.time()
        })


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = settings.api.max_body_bytes
    # Preserve insertion order in JSON responses (do not alphabetically sort keys).
    app.config["JSON_SORT_KEYS"] = False
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
            jsonify(
                {
                    "ok": False,
                    "error": {
                        "code": err.code,
                        "message": err.message,
                    },
                    "request_id": g.get("request_id"),
                }
            ),
            err.status_code,
        )

    @app.errorhandler(413)
    def _handle_too_large(_err):  # type: ignore[no-untyped-def]
        return (
            jsonify(
                {
                    "ok": False,
                    "error": {
                        "code": "payload_too_large",
                        "message": "Request body is too large.",
                    },
                    "request_id": g.get("request_id"),
                }
            ),
            413,
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(err: Exception):  # type: ignore[no-untyped-def]
        logger.exception("Unhandled API error [request_id=%s]: %s", g.get("request_id"), err)
        return (
            jsonify(
                {
                    "ok": False,
                    "error": {
                        "code": "internal_error",
                        "message": "Internal server error.",
                    },
                    "request_id": g.get("request_id"),
                }
            ),
            500,
        )

    @app.get("/api/status/<job_id>")
    def get_status_endpoint(job_id: str): # type: ignore[no-untyped-def]
        job = job_manager.get_job(job_id)
        if not job:
            raise ApiError("Job not found.", status_code=404, code="not_found")
        
        return jsonify({
            "ok": True,
            "job_id": job["id"],
            "status": job["status"],
            "error": job.get("error"),
            "result": job.get("result"),
            "submitted_at": job.get("submitted_at"),
            "finished_at": job.get("finished_at")
        }), 200

    @app.post("/api/run-qa")
    def run_qa_endpoint():  # type: ignore[no-untyped-def]
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

        job_id = job_manager.create_job(config=cfg, request_id=g.get("request_id"))

        logger.info(
            "Enqueued QA run [job_id=%s, request_id=%s, url=%s]",
            job_id,
            g.get("request_id"),
            parsed["url"]
        )

        # Start background thread
        thread = threading.Thread(
            target=_run_qa_background,
            args=(job_id, cfg, parsed["timeout_seconds"]),
            daemon=True
        )
        thread.start()

        return (
            jsonify(
                {
                    "ok": True,
                    "job_id": job_id,
                    "request_id": g.get("request_id"),
                    "status": "pending",
                    "message": "QA run enqueued successfully."
                }
            ),
            202,
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host=os.getenv("HOST", settings.api.host),
        port=int(os.getenv("PORT", str(settings.api.port)))
    )
