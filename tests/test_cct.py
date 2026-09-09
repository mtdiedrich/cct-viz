"""Acceptance tests for the CCT engine (spec section 11.1-11.5)."""

from __future__ import annotations

import chess

from cct_viz import cct


def sans(candidates) -> list[str]:
    return [c.san for c in candidates]


def test_start_position_nothing_forcing():
    # spec 11.1
    board = chess.Board("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
    report = cct.analyse(board)
    assert sans(report.checks) == []
    assert sans(report.captures) == []
    assert sans(report.threats) == []


def test_after_e4_three_pawn_threats():
    # spec 11.2
    board = chess.Board("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1")
    report = cct.analyse(board)
    assert sans(report.checks) == []
    assert sans(report.captures) == []
    assert sans(report.threats) == ["Nf6", "d5", "f5"]
    for candidate in report.threats:
        assert len(candidate.gains) == 1
        gain = candidate.gains[0]
        assert gain.kind == "hanging"
        assert gain.score == 1
        assert gain.square == "e4"


def test_scholars_mate_checks_and_captures():
    # spec 11.3
    board = chess.Board(
        "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4"
    )
    report = cct.analyse(board)
    assert sans(report.checks) == ["Qxf7#", "Bxf7+", "Qxe5+"]
    assert sans(report.captures) == ["Bxf7+", "Qxe5+", "Qxf7#", "Qxh7"]
    assert sans(report.threats) == []


def test_opera_game_before_bc4():
    # spec 11.4
    board = chess.Board(
        "rn1qkbnr/ppp2ppp/8/4p3/4P3/5Q2/PPP2PPP/RNB1KB1R w KQkq - 0 6"
    )
    report = cct.analyse(board)

    assert sans(report.checks) == ["Qxf7+", "Bb5+"]
    assert sans(report.captures) == ["Qxf7+"]
    assert report.counts["threats"] == 11

    assert report.threats[0].san == "Bc4"
    assert report.threats[0].gains[0].kind == "mate"
    assert report.threats[0].gains[0].san == "Qxf7#"
    assert report.threats[0].gains[0].text == "threatens mate: Qxf7#"

    assert report.threats[1].san == "Bg5"
    assert report.threats[1].gains[0].kind == "favourable"
    assert report.threats[1].gains[0].score == 9

    rest = sans(report.threats[2:])
    assert rest == ["Ba6", "Bf4", "Qb3", "Qc3", "Qf4", "Qf5", "Qf6", "Qg3", "Qh5"]
    for candidate in report.threats[2:]:
        assert candidate.score == 1


def test_board_purity():
    # spec 11.5
    board = chess.Board(
        "rn1qkbnr/ppp2ppp/8/4p3/4P3/5Q2/PPP2PPP/RNB1KB1R w KQkq - 0 6"
    )
    fen_before = board.fen()
    stack_before = len(board.move_stack)
    cct.analyse(board)
    assert board.fen() == fen_before
    assert len(board.move_stack) == stack_before


def test_a_capture_that_is_also_check_appears_in_both_lists():
    board = chess.Board(
        "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4"
    )
    report = cct.analyse(board)
    assert "Bxf7+" in sans(report.checks)
    assert "Bxf7+" in sans(report.captures)
