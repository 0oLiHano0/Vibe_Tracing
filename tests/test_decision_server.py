"""
End-to-end tests for the Decision Server API (EVO-TASK-013).

Tests the Flask app's three endpoints using the test client:
  - GET  /api/decisions
  - POST /api/decisions
  - GET  /api/pending

Also tests the src/vibe_tracing/decision_server.py module which has
strict field validation and integer decision IDs.
"""

import json
from pathlib import Path

import pytest

import decision_server
from decision_server import app


@pytest.fixture(autouse=True)
def _isolate_decisions_path(tmp_path, monkeypatch):
    """Redirect DECISIONS_PATH to a temp directory so tests never touch real data."""
    isolated = tmp_path / ".vibetracing" / "human_decisions.json"
    monkeypatch.setattr(decision_server, "DECISIONS_PATH", isolated)


@pytest.fixture()
def client():
    """Provide a Flask test client with TESTING mode on."""
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ======================================================================
# Tests for src/vibe_tracing/decision_server.py  (strict validation)
# ======================================================================

from vibe_tracing.decision_server import app as src_app
import vibe_tracing.decision_server as src_ds


@pytest.fixture(autouse=True)
def _isolate_src_decisions(tmp_path, monkeypatch):
    """Redirect the src module's _DECISIONS_FILE to a temp directory."""
    isolated = tmp_path / ".vibetracing" / "human_decisions.json"
    monkeypatch.setattr(src_ds, "_DECISIONS_FILE", isolated)


@pytest.fixture()
def src_client():
    """Provide a Flask test client for the src decision server."""
    src_app.config["TESTING"] = True
    with src_app.test_client() as c:
        yield c


# ------------------------------------------------------------------
# GET /api/decisions
# ------------------------------------------------------------------

def test_get_decisions_empty(client):
    """GET /api/decisions returns an empty list when no decisions exist."""
    resp = client.get("/api/decisions")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["version"] == "1.0"
    assert data["decisions"] == []


# ------------------------------------------------------------------
# POST /api/decisions
# ------------------------------------------------------------------

def test_post_decision(client):
    """POST /api/decisions records a decision and returns it."""
    payload = {
        "category": "accepted_rule",
        "target_id": "GATE-VT-004",
        "action": "reconfirm",
        "reason": "Still valid",
    }
    resp = client.post("/api/decisions", json=payload)
    assert resp.status_code == 200

    data = json.loads(resp.data)
    assert data["status"] == "ok"
    assert data["decision"]["decision_id"] is not None
    assert data["decision"]["category"] == "accepted_rule"
    assert data["decision"]["target_id"] == "GATE-VT-004"
    assert data["decision"]["action"] == "reconfirm"
    assert data["decision"]["reason"] == "Still valid"
    assert data["decision"]["decided_by"] == "product_owner"


def test_post_decision_auto_id(client):
    """Decision IDs auto-increment when not supplied (DEC-001, DEC-002, ...)."""
    resp1 = client.post("/api/decisions", json={"category": "c1"})
    id1 = json.loads(resp1.data)["decision"]["decision_id"]
    assert id1 == "DEC-001"

    resp2 = client.post("/api/decisions", json={"category": "c2"})
    id2 = json.loads(resp2.data)["decision"]["decision_id"]
    assert id2 == "DEC-002"


def test_post_decision_custom_id(client):
    """A supplied decision_id is used as-is instead of auto-generation."""
    resp = client.post(
        "/api/decisions",
        json={"decision_id": "CUSTOM-42", "category": "test"},
    )
    data = json.loads(resp.data)
    assert data["decision"]["decision_id"] == "CUSTOM-42"


# ------------------------------------------------------------------
# GET /api/decisions  (after posting)
# ------------------------------------------------------------------

def test_get_decisions_after_post(client):
    """GET /api/decisions returns previously posted decisions."""
    client.post(
        "/api/decisions",
        json={
            "category": "uncovered_ac",
            "target_id": "AC-003",
            "action": "accept_gap",
            "reason": "OK for now",
        },
    )
    resp = client.get("/api/decisions")
    data = json.loads(resp.data)
    assert data["version"] == "1.0"
    assert len(data["decisions"]) == 1
    assert data["decisions"][0]["target_id"] == "AC-003"
    assert data["decisions"][0]["category"] == "uncovered_ac"


def test_get_decisions_multiple(client):
    """Multiple decisions accumulate correctly."""
    for i in range(3):
        client.post("/api/decisions", json={"category": f"cat-{i}"})
    data = json.loads(client.get("/api/decisions").data)
    assert len(data["decisions"]) == 3
    categories = [d["category"] for d in data["decisions"]]
    assert categories == ["cat-0", "cat-1", "cat-2"]


# ------------------------------------------------------------------
# GET /api/pending
# ------------------------------------------------------------------

def test_get_pending(client):
    """GET /api/pending returns 200 with pending decisions from traceability report."""
    resp = client.get("/api/pending")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert "pending" in data
    assert isinstance(data["pending"], list)
    assert "total" in data
    assert isinstance(data["total"], int)


# ------------------------------------------------------------------
# Persistence: decisions survive across requests
# ------------------------------------------------------------------

def test_decisions_persist_across_requests(client):
    """Decisions are written to disk and survive across separate requests."""
    client.post("/api/decisions", json={"category": "persist", "target_id": "X"})

    # A fresh GET should still see the decision (loaded from disk)
    resp = client.get("/api/decisions")
    data = json.loads(resp.data)
    assert any(d["target_id"] == "X" for d in data["decisions"])


# ======================================================================
# src/vibe_tracing/decision_server.py -- strict validation & integer IDs
# ======================================================================


class TestSrcDecisionServerGetEmpty:
    """GET /api/decisions on the src module returns an empty list when no decisions exist."""

    def test_get_empty_returns_empty_list(self, src_client):
        resp = src_client.get("/api/decisions")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data == []


class TestSrcDecisionServerPostAndGet:
    """POST then GET returns the decision; multiple POSTs accumulate."""

    def test_post_then_get_includes_decision(self, src_client):
        """After POSTing a decision, GET returns it in the array."""
        payload = {
            "category": "accepted_rule",
            "targetId": "GATE-VT-004",
            "action": "reconfirm",
            "reason": "Still valid",
            "decidedBy": "product_owner",
        }
        resp = src_client.post("/api/decisions", json=payload)
        assert resp.status_code == 201
        post_data = json.loads(resp.data)
        assert post_data["success"] is True
        assert post_data["decision_id"] == 1

        # GET should return it
        get_resp = src_client.get("/api/decisions")
        decisions = json.loads(get_resp.data)
        assert len(decisions) == 1
        assert decisions[0]["category"] == "accepted_rule"
        assert decisions[0]["targetId"] == "GATE-VT-004"
        assert decisions[0]["decision_id"] == 1

    def test_multiple_post_accumulates(self, src_client):
        """Multiple POSTs accumulate -- GET returns all of them."""
        for i in range(3):
            src_client.post(
                "/api/decisions",
                json={
                    "category": f"cat-{i}",
                    "targetId": f"T-{i}",
                    "action": "approve",
                    "reason": "ok",
                    "decidedBy": "tester",
                },
            )
        decisions = json.loads(src_client.get("/api/decisions").data)
        assert len(decisions) == 3
        categories = [d["category"] for d in decisions]
        assert categories == ["cat-0", "cat-1", "cat-2"]


class TestSrcDecisionServerAutoIncrement:
    """decision_id auto-increments: first is 1, second is 2."""

    def test_first_decision_id_is_one(self, src_client):
        resp = src_client.post(
            "/api/decisions",
            json={
                "category": "c1",
                "targetId": "T1",
                "action": "approve",
                "reason": "r",
                "decidedBy": "user",
            },
        )
        assert json.loads(resp.data)["decision_id"] == 1

    def test_second_decision_id_is_two(self, src_client):
        for i in range(2):
            src_client.post(
                "/api/decisions",
                json={
                    "category": f"c{i}",
                    "targetId": f"T{i}",
                    "action": "approve",
                    "reason": "r",
                    "decidedBy": "user",
                },
            )
        decisions = json.loads(src_client.get("/api/decisions").data)
        assert decisions[0]["decision_id"] == 1
        assert decisions[1]["decision_id"] == 2


class TestSrcDecisionServerValidation:
    """POST with missing required fields returns 400."""

    def test_missing_all_fields_returns_400(self, src_client):
        """An empty JSON body should return 400 with missing fields error."""
        resp = src_client.post("/api/decisions", json={})
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert data["success"] is False
        assert "missing fields" in data["error"]

    def test_missing_some_fields_returns_400(self, src_client):
        """Missing some required fields returns 400."""
        resp = src_client.post(
            "/api/decisions",
            json={"category": "test", "action": "approve"},
        )
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert data["success"] is False
        assert "missing fields" in data["error"]

    def test_all_fields_present_succeeds(self, src_client):
        """All five required fields present returns 201."""
        resp = src_client.post(
            "/api/decisions",
            json={
                "category": "test",
                "targetId": "T-1",
                "action": "approve",
                "reason": "looks good",
                "decidedBy": "tester",
            },
        )
        assert resp.status_code == 201
        assert json.loads(resp.data)["success"] is True
