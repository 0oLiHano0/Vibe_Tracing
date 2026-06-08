"""VT Decision Server — minimal API for human decision tracking.

Provides a lightweight backend so the static VT dashboard can record
human decisions (approve / reject / override) to a local JSON file.

Endpoints:
    GET  /api/decisions  — return all recorded decisions
    POST /api/decisions  — record a new decision
    GET  /api/pending    — return pending decisions (placeholder)

Usage:
    python3 decision_server.py [--port PORT]
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DECISIONS_PATH = Path(".vibetracing/human_decisions.json")


def _load_decisions():
    """Load existing decisions from disk, or return an empty structure."""
    if not DECISIONS_PATH.exists():
        return {"version": "1.0", "decisions": []}
    return json.loads(DECISIONS_PATH.read_text(encoding="utf-8"))


def _save_decisions(data):
    """Persist decisions to disk, creating parent dirs if needed."""
    DECISIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    DECISIONS_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------

@app.route("/api/decisions", methods=["GET"])
def get_decisions():
    """Return every recorded decision."""
    return jsonify(_load_decisions())


@app.route("/api/decisions", methods=["POST"])
def post_decision():
    """Record a new human decision.

    Expected JSON body (all fields optional except those with defaults):
        decision_id  — auto-generated if omitted (DEC-001, DEC-002, ...)
        category     — e.g. "requirement_change", "scope_adjustment"
        target_id    — ID of the entity this decision applies to
        action       — e.g. "approve", "reject", "override"
        reason       — free-text justification
        decided_by   — who made the decision (default: "product_owner")
    """
    body = request.get_json(force=True)
    data = _load_decisions()

    decision = {
        "decision_id": body.get(
            "decision_id", f"DEC-{len(data['decisions']) + 1:03d}"
        ),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "category": body.get("category", ""),
        "target_id": body.get("target_id", ""),
        "action": body.get("action", ""),
        "reason": body.get("reason", ""),
        "decided_by": body.get("decided_by", "product_owner"),
    }

    data["decisions"].append(decision)
    _save_decisions(data)
    return jsonify({"status": "ok", "decision": decision})


@app.route("/api/pending", methods=["GET"])
def get_pending():
    """Return pending decisions placeholder.

    Actual pending-decision logic will be implemented in a future task
    by cross-referencing dashboard evidence with recorded decisions.
    """
    return jsonify({"pending": [], "note": "Use dashboard for pending decisions"})


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="VT Decision Server")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    app.run(port=args.port, debug=True)
