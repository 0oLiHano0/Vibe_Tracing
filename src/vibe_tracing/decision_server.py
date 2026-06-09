"""VT Decision Server -- receives human decisions for the Dashboard."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app, origins=["http://localhost:*", "http://127.0.0.1:*"])

_DECISIONS_FILE = Path(".vibetracing/human_decisions.json")


def _load_decisions() -> list[dict]:
    if _DECISIONS_FILE.exists():
        data = json.loads(_DECISIONS_FILE.read_text(encoding="utf-8"))
        return data.get("decisions", [])
    return []


def _save_decisions(decisions: list[dict]) -> None:
    _DECISIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _DECISIONS_FILE.write_text(
        json.dumps({"decisions": decisions}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _next_decision_id(decisions: list[dict]) -> int:
    if not decisions:
        return 1
    return max(d["decision_id"] for d in decisions) + 1


@app.route("/api/decisions", methods=["GET"])
def get_decisions():
    return jsonify(_load_decisions())


@app.route("/api/decisions", methods=["POST"])
def post_decision():
    body = request.get_json(force=True)
    required = ("category", "targetId", "action", "reason", "decidedBy")
    missing = [k for k in required if k not in body]
    if missing:
        return jsonify({"success": False, "error": f"missing fields: {missing}"}), 400

    decisions = _load_decisions()
    new_id = _next_decision_id(decisions)
    entry = {
        "decision_id": new_id,
        "category": body["category"],
        "targetId": body["targetId"],
        "action": body["action"],
        "reason": body["reason"],
        "decidedBy": body["decidedBy"],
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    decisions.append(entry)
    _save_decisions(decisions)
    return jsonify({"success": True, "decision_id": new_id}), 201


def main():
    _DECISIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not _DECISIONS_FILE.exists():
        _save_decisions([])
    app.run(host="0.0.0.0", port=5000, debug=True)


if __name__ == "__main__":
    main()
