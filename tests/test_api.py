"""Acceptance tests for the HTTP API (spec section 11.7)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from cct_viz.server import app

client = TestClient(app)

EXAMPLE_PGN = (
    Path(__file__).resolve().parents[1] / "src" / "cct_viz" / "static" / "example.pgn"
).read_text()


def test_post_game_ok():
    resp = client.post("/api/game", json={"pgn": EXAMPLE_PGN})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["games"]) == 1
    assert len(body["game"]["plies"]) == 34
    assert body["selected_index"] == 0
    # `from` / `to` aliases must be present on candidates
    first_threats = body["game"]["plies"][10]["cct"]["threats"]
    if first_threats:
        assert "from" in first_threats[0]
        assert "to" in first_threats[0]


def test_post_game_empty():
    resp = client.post("/api/game", json={"pgn": "   "})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "PGN_EMPTY"


def test_post_game_index_out_of_range():
    resp = client.post("/api/game", json={"pgn": EXAMPLE_PGN, "game_index": 5})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "GAME_INDEX_OUT_OF_RANGE"


def test_post_game_illegal_move():
    resp = client.post("/api/game", json={"pgn": '[Event "x"]\n\n1. e4 e5 2. Ke3 *'})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "PGN_PARSE_ERROR"


def test_post_two_games():
    two = EXAMPLE_PGN + "\n\n" + EXAMPLE_PGN
    resp = client.post("/api/game", json={"pgn": two})
    assert resp.status_code == 200
    assert len(resp.json()["games"]) == 2

    resp2 = client.post("/api/game", json={"pgn": two, "game_index": 1})
    assert resp2.status_code == 200
    assert resp2.json()["selected_index"] == 1


def test_health():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["version"] == "0.1.0"


def test_index_html():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert 'id="board"' in resp.text
