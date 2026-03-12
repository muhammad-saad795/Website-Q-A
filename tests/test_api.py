import json
from unittest.mock import patch


class TestHealthEndpoint:
    def test_health(self, flask_client):
        resp = flask_client.get("/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True


class TestRunQAEndpoint:
    def test_missing_json(self, flask_client):
        resp = flask_client.post("/api/run-qa", data="not json")
        assert resp.status_code == 400

    def test_missing_url(self, flask_client):
        resp = flask_client.post("/api/run-qa",
                                 data=json.dumps({}),
                                 content_type="application/json")
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "missing_url"

    def test_ssrf_localhost_blocked(self, flask_client):
        resp = flask_client.post("/api/run-qa",
                                 data=json.dumps({"url": "http://localhost/admin"}),
                                 content_type="application/json")
        assert resp.status_code == 400
        assert "localhost" in resp.get_json()["error"]["message"].lower()

    def test_ssrf_private_ip_blocked(self, flask_client):
        resp = flask_client.post("/api/run-qa",
                                 data=json.dumps({"url": "http://192.168.1.1/admin"}),
                                 content_type="application/json")
        assert resp.status_code == 400
        assert "private" in resp.get_json()["error"]["message"].lower() or "reserved" in resp.get_json()["error"]["message"].lower()

    def test_ssrf_ftp_blocked(self, flask_client):
        resp = flask_client.post("/api/run-qa",
                                 data=json.dumps({"url": "ftp://files.example.com/data"}),
                                 content_type="application/json")
        assert resp.status_code == 400
        assert "scheme" in resp.get_json()["error"]["message"].lower()

    @patch("app._run_qa_background")
    def test_valid_url_accepted(self, mock_bg, flask_client):
        resp = flask_client.post("/api/run-qa",
                                 data=json.dumps({"url": "https://example.com", "max_pages": 1}),
                                 content_type="application/json")
        assert resp.status_code == 202
        data = resp.get_json()
        assert data["ok"] is True
        assert "job_id" in data


class TestStatusEndpoint:
    def test_not_found(self, flask_client):
        resp = flask_client.get("/api/status/nonexistent-id")
        assert resp.status_code == 404


class TestJobsEndpoint:
    def test_list_jobs(self, flask_client):
        resp = flask_client.get("/api/jobs")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert isinstance(data["jobs"], list)


class TestCancelEndpoint:
    def test_cancel_nonexistent(self, flask_client):
        resp = flask_client.post("/api/jobs/fake-id/cancel")
        assert resp.status_code == 404
