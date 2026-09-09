"""Acceptance tests for full-game analysis (spec section 11.6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cct_viz import pgn

EXAMPLE_PGN = (
    Path(__file__).resolve().parents[1] / "src" / "cct_viz" / "static" / "example.pgn"
).read_text()


def test_full_game_analysis():
    game = pgn.analyse_game(EXAMPLE_PGN, 0)

    assert game.ply_count == 33
    assert len(game.plies) == 34

    assert game.plies[0].san == "e4"
    assert game.plies[0].turn == "w"
    assert game.plies[0].last_move is None

    assert game.plies[32].san == "Rd8#"
    assert game.plies[33].san is None
    assert game.plies[33].uci is None
    assert game.plies[33].is_checkmate is True

    mate_candidates = [c for c in game.plies[32].cct.checks if c.san == "Rd8#"]
    assert mate_candidates, "Rd8# must be enumerated as a check"
    assert mate_candidates[0].played is True
    assert mate_candidates[0].is_mate is True


def test_list_games_single():
    games = pgn.list_games(EXAMPLE_PGN)
    assert len(games) == 1
    assert games[0].white == "Paul Morphy"
    assert games[0].result == "1-0"
    assert games[0].ply_count == 33


def test_two_games_concatenated():
    games = pgn.list_games(EXAMPLE_PGN + "\n\n" + EXAMPLE_PGN)
    assert len(games) == 2
    assert games[1].index == 1


def test_empty_pgn_raises():
    with pytest.raises(pgn.PgnError) as info:
        pgn.analyse_game("   ")
    assert info.value.code == "PGN_EMPTY"


def test_illegal_move_raises_parse_error():
    with pytest.raises(pgn.PgnError) as info:
        pgn.analyse_game('[Event "x"]\n\n1. e4 e5 2. Ke3 *')
    assert info.value.code == "PGN_PARSE_ERROR"


def test_unsupported_variant_raises():
    crazy = '[Event "x"]\n[Variant "Crazyhouse"]\n\n1. e4 e5 *'
    with pytest.raises(pgn.PgnError) as info:
        pgn.analyse_game(crazy)
    assert info.value.code == "UNSUPPORTED_VARIANT"
