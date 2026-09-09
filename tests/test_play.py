"""Acceptance tests for Play Mode (play-mode spec section 11).

Every expected value below was produced by the CCT engine currently in this
repo. They are exact, not illustrative.
"""

from __future__ import annotations

import chess
import pytest
from fastapi.testclient import TestClient

from cct_viz.play import MAX_PLAY_MOVES, PlayError, build_node
from cct_viz.server import app

client = TestClient(app)


def _post(body: dict):
    return client.post("/api/play", json=body)


def _sans(candidates: list[dict]) -> list[str]:
    return [c["san"] for c in candidates]


# --------------------------------------------------------------------------- #
# 11.1 Start position — both sides quiet
# --------------------------------------------------------------------------- #


def test_start_position_both_sides_quiet():
    resp = _post({"moves": [], "analyse_from": 0})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["plies"]) == 1

    node = body["plies"][0]
    assert node["index"] == 0
    assert node["turn"] == "w"
    assert node["move_number"] == 1
    assert node["san"] is None
    assert node["last_move"] is None
    assert node["is_game_over"] is False
    assert len(node["legal_moves"]) == 20

    assert node["cct"]["w"]["to_move"] is True
    assert node["cct"]["b"]["to_move"] is False
    for color in ("w", "b"):
        side = node["cct"][color]
        assert side["available"] is True
        rep = side["report"]
        assert rep["counts"] == {"checks": 0, "captures": 0, "threats": 0}
        assert rep["checks"] == []
        assert rep["captures"] == []
        assert rep["threats"] == []


# --------------------------------------------------------------------------- #
# 11.2 After 1.e4 — the waiting side is the interesting one
# --------------------------------------------------------------------------- #


def test_after_e4_waiting_side_threats():
    resp = _post({"moves": ["e2e4"], "analyse_from": 0})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["plies"]) == 2

    node = body["plies"][1]
    assert node["turn"] == "b"
    assert node["san"] == "e4"
    assert node["last_move"] == {"from": "e2", "to": "e4"}

    black = node["cct"]["b"]
    assert black["report"]["counts"] == {"checks": 0, "captures": 0, "threats": 3}
    threats = black["report"]["threats"]
    assert _sans(threats) == ["Nf6", "d5", "f5"]
    assert [t["score"] for t in threats] == [1, 1, 1]
    assert [t["gains"][0]["text"] for t in threats] == [
        "wins a hanging piece on e4: Nxe4",
        "wins a hanging piece on e4: dxe4",
        "wins a hanging piece on e4: fxe4",
    ]

    white = node["cct"]["w"]
    assert white["available"] is True
    assert white["report"]["counts"] == {"checks": 0, "captures": 0, "threats": 0}


# --------------------------------------------------------------------------- #
# 11.3 Scholar's mate — the in-check guard
# --------------------------------------------------------------------------- #

SCHOLARS = ["e2e4", "e7e5", "f1c4", "b8c6", "d1h5", "g8f6", "h5f7"]


def test_scholars_mate_in_check_guard():
    resp = _post({"moves": SCHOLARS, "analyse_from": 0})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["plies"]) == 8

    node = body["plies"][7]
    assert node["fen"] == (
        "r1bqkb1r/pppp1Qpp/2n2n2/4p3/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 0 4"
    )
    assert node["turn"] == "b"
    assert node["in_check"] is True
    assert node["is_checkmate"] is True
    assert node["is_game_over"] is True
    assert node["over_reason"] == "checkmate"
    assert node["result"] == "1-0"
    assert node["legal_moves"] == []

    black = node["cct"]["b"]
    assert black["available"] is True
    assert black["report"]["checks"] == []
    assert black["report"]["captures"] == []
    assert black["report"]["threats"] == []
    assert black["report"]["counts"] == {"checks": 0, "captures": 0, "threats": 0}

    white = node["cct"]["w"]
    assert white["available"] is False
    assert white["report"] is None
    assert white["reason"] == "side_to_move_in_check"


# --------------------------------------------------------------------------- #
# 11.4 The `played` flag
# --------------------------------------------------------------------------- #


def test_played_flag():
    resp = _post({"moves": SCHOLARS, "analyse_from": 6})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["plies"]) == 1

    node = body["plies"][0]
    assert node["index"] == 6
    assert node["turn"] == "w"

    checks = node["cct"]["w"]["report"]["checks"]
    assert _sans(checks) == ["Qxf7#", "Bxf7+", "Qxe5+"]
    assert [c["played"] for c in checks] == [True, False, False]

    captures = node["cct"]["w"]["report"]["captures"]
    assert _sans(captures) == ["Bxf7+", "Qxe5+", "Qxf7#", "Qxh7"]
    assert [c["played"] for c in captures] == [False, False, True, False]

    black = node["cct"]["b"]
    assert black["available"] is True
    assert black["report"]["counts"] == {"checks": 0, "captures": 2, "threats": 5}
    for kind in ("checks", "captures", "threats"):
        for c in black["report"][kind]:
            assert c["played"] is False


# --------------------------------------------------------------------------- #
# 11.5 Starting from a FEN — both sides busy
# --------------------------------------------------------------------------- #

FEN_5 = "rn1qkb1r/ppp2ppp/5n2/4p3/2B1P3/1Q6/PPP2PPP/RNB1K2R b KQkq - 3 7"


def test_start_from_fen_both_sides_busy():
    resp = _post({"start_fen": FEN_5, "moves": [], "analyse_from": 0})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["plies"]) == 1

    node = body["plies"][0]
    assert node["turn"] == "b"
    assert node["move_number"] == 7

    black = node["cct"]["b"]["report"]
    assert black["counts"] == {"checks": 3, "captures": 1, "threats": 2}
    assert _sans(black["checks"]) == ["Bb4+", "Qd1+", "Qd2+"]
    assert _sans(black["captures"]) == ["Nxe4"]
    assert _sans(black["threats"]) == ["Qd3", "b5"]
    assert [t["score"] for t in black["threats"]] == [3, 3]
    assert [t["gains"][0]["text"] for t in black["threats"]] == [
        "double attack from d3 on b3 and c4",
        "wins material on c4: bxc4",
    ]

    white = node["cct"]["w"]
    assert white["available"] is True
    assert white["report"]["counts"] == {"checks": 4, "captures": 2, "threats": 4}
    assert _sans(white["report"]["checks"]) == ["Bxf7+", "Bb5+", "Qa4+", "Qb5+"]
    assert _sans(white["report"]["threats"]) == ["Bf4", "Qc3", "Qg3", "f4"]


# --------------------------------------------------------------------------- #
# 11.6 Errors
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "body, code",
    [
        ({"moves": ["e2e5"]}, "ILLEGAL_MOVE"),
        ({"moves": ["zzzz"]}, "ILLEGAL_MOVE"),
        ({"start_fen": "not a fen"}, "BAD_FEN"),
        ({"start_fen": "R3k3/8/8/8/8/8/8/4K3 w - - 0 1"}, "BAD_FEN"),
        ({"moves": ["e2e4"], "analyse_from": 5}, "BAD_ANALYSE_FROM"),
        ({"moves": ["e2e4"], "analyse_from": -1}, "BAD_ANALYSE_FROM"),
        ({"moves": ["a2a3"] * 301}, "MOVES_TOO_LONG"),
    ],
)
def test_errors(body, code):
    resp = _post(body)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == code


def test_illegal_move_message_names_move_and_ply():
    resp = _post({"moves": ["e2e5"]})
    assert resp.json()["error"]["message"] == "Illegal move 'e2e5' at ply 0."


# --------------------------------------------------------------------------- #
# 11.7 Purity
# --------------------------------------------------------------------------- #


def test_build_node_does_not_mutate_board():
    board = chess.Board()
    fen_before = board.fen()
    stack_before = len(board.move_stack)

    build_node(board, index=0, san=None, uci=None, incoming=None, played=None)

    assert board.fen() == fen_before
    assert len(board.move_stack) == stack_before


def test_max_play_moves_is_300():
    assert MAX_PLAY_MOVES == 300


# --------------------------------------------------------------------------- #
# 11.8 Regression — the two pages
# --------------------------------------------------------------------------- #


def test_index_and_play_pages():
    root = client.get("/")
    assert root.status_code == 200
    assert "text/html" in root.headers["content-type"]

    play = client.get("/play")
    assert play.status_code == 200
    assert "text/html" in play.headers["content-type"]
    assert 'id="board"' in play.text


# --------------------------------------------------------------------------- #
# Extra coverage of the selective-analysis contract (spec 5.5 / 10)
# --------------------------------------------------------------------------- #


def test_analyse_from_tip_returns_single_node():
    resp = _post({"moves": ["e2e4", "e7e5"], "analyse_from": 2})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ply_count"] == 2
    assert body["analyse_from"] == 2
    assert len(body["plies"]) == 1
    assert body["plies"][0]["index"] == 2


def test_start_fen_is_normalised_in_response():
    resp = _post({"moves": [], "analyse_from": 0})
    assert resp.json()["start_fen"] == chess.Board().fen()
