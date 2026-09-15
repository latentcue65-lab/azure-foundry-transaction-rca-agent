import json
import uuid

from fastapi.testclient import TestClient

from rca_agent.api import create_app
from rca_agent.seed import sample_request


def test_http_application_contract_and_audit(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get("/").status_code == 200
        assert client.get("/health").json()["mode"] == "replay"
        response = client.post("/api/analyze", json=sample_request())
        assert response.status_code == 200, response.text
        assert len(response.json()) == 6
        assert response.headers["X-RCA-Mode"] == "replay"
        audit = client.get("/api/investigations/" + response.headers["X-Investigation-Id"])
        assert audit.status_code == 200
        assert audit.json()["diagnostics"]["outcome"] == "completed"
        assert client.get("/api/investigations/not-a-uuid").status_code == 422
        assert client.post("/api/analyze", json=sample_request("TX9999")).status_code == 404
        request = sample_request()
        request["transactionId"] = None
        assert client.post("/api/analyze", json=request).status_code == 409


def test_missing_foundry_configuration_does_not_appear_as_live_success(settings):
    config = settings.model_copy(update={"mode": "foundry", "project_endpoint": "", "model_name": ""})
    with TestClient(create_app(config)) as client:
        response = client.post("/api/analyze", json=sample_request())
        assert response.status_code == 503
        assert "FOUNDRY_PROJECT_ENDPOINT" in response.json()["detail"]


def test_history_filters_customer_and_omits_evidence_and_damaged_files(settings):
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/analyze", json=sample_request())
        run_id = response.headers["X-Investigation-Id"]
        audit = client.get("/api/investigations/" + run_id).json()
        other = json.loads(json.dumps(audit))
        other["report"]["customerId"] = "C2001"
        (settings.output_dir / f"{uuid.uuid4()}.json").write_text(json.dumps(other))
        (settings.output_dir / f"{uuid.uuid4()}.json").write_text("{broken")
        (settings.output_dir / "evaluation-replay.json").write_text("{}")
        response = client.get("/api/investigations", params={"customerId": "C1001", "limit": 1})
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        rows = response.json()
        assert len(rows) == 1 and rows[0]["investigationId"] == run_id
        assert "report" not in rows[0] and "evidence" not in rows[0]
        assert client.get("/api/investigations?customerId=unknown").json() == []
        assert client.get("/api/investigations?customerId=C1001&limit=101").status_code == 422
        assert client.get("/api/investigations").status_code == 422


def test_ui_assets_are_served_under_content_security_policy(settings):
    with TestClient(create_app(settings)) as client:
        page = client.get("/")
        assert "'unsafe-inline'" not in page.headers["content-security-policy"]
        assert client.get("/static/app.js").status_code == 200
        assert client.get("/static/app.css").status_code == 200
