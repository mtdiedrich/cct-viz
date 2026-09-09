"""PGN parsing + full-game analysis (spec section 8).

Rules:

* Mainline only — variations (RAVs) and NAGs are ignored.
* ``node.comment`` is kept verbatim (whitespace stripped) on the node the move
  is played *from*.
* Non-standard start positions are honoured via ``game.board()``.
* A game with more than 600 plies, or a non-standard ``Variant`` header, is
  rejected.
* ``ply_count + 1`` ``Node`` objects are emitted; the final node has
  ``san = uci = None`` but still carries a full CCT report.
"""

from __future__ import annotations

import io

import chess
import chess.pgn

from . import cct
from .models import AnalysedGame, GameResponse, GameSummary, Node

MAX_PLIES = 600
_STANDARD_VARIANTS = {"standard", "chess", "normal", ""}


class PgnError(Exception):
    """A user-facing PGN problem. ``code`` is one of the spec's error codes."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _require_text(pgn_text: str | None) -> str:
    if pgn_text is None or not pgn_text.strip():
        raise PgnError("PGN_EMPTY", "No PGN text was provided.")
    return pgn_text


def _read_all_games(pgn_text: str) -> list[chess.pgn.Game]:
    stream = io.StringIO(pgn_text)
    games: list[chess.pgn.Game] = []
    while True:
        game = chess.pgn.read_game(stream)
        if game is None:
            break
        games.append(game)
    return games


def _parse_games(pgn_text: str) -> list[chess.pgn.Game]:
    games = _read_all_games(pgn_text)
    if not games:
        raise PgnError("PGN_NO_GAMES", "The text parsed but contained zero games.")
    return games


def _mainline_moves(game: chess.pgn.Game) -> list[chess.Move]:
    return list(game.mainline_moves())


def _summary(game: chess.pgn.Game, index: int) -> GameSummary:
    headers = game.headers
    return GameSummary(
        index=index,
        white=headers.get("White", "?"),
        black=headers.get("Black", "?"),
        event=headers.get("Event", "?"),
        site=headers.get("Site", "?"),
        date=headers.get("Date", "????.??.??"),
        round=headers.get("Round", "?"),
        result=headers.get("Result", "*"),
        eco=headers.get("ECO", ""),
        ply_count=len(_mainline_moves(game)),
    )


def _guard_variant(game: chess.pgn.Game) -> None:
    variant = game.headers.get("Variant")
    if variant is not None and variant.strip().lower() not in _STANDARD_VARIANTS:
        raise PgnError("UNSUPPORTED_VARIANT", f"Unsupported variant: {variant}")


def _select_game(games: list[chess.pgn.Game], game_index: int) -> chess.pgn.Game:
    if game_index < 0 or game_index >= len(games):
        raise PgnError(
            "GAME_INDEX_OUT_OF_RANGE",
            f"game_index {game_index} is out of range (0..{len(games) - 1}).",
        )
    return games[game_index]


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def list_games(pgn_text: str | None) -> list[GameSummary]:
    text = _require_text(pgn_text)
    return [_summary(g, i) for i, g in enumerate(_parse_games(text))]


def analyse_game(pgn_text: str | None, game_index: int = 0) -> AnalysedGame:
    text = _require_text(pgn_text)
    games = _parse_games(text)
    game = _select_game(games, game_index)

    _guard_variant(game)
    if game.errors:
        raise PgnError("PGN_PARSE_ERROR", str(game.errors[0]))

    moves = _mainline_moves(game)
    if len(moves) > MAX_PLIES:
        raise PgnError(
            "GAME_TOO_LONG",
            f"Game has {len(moves)} plies; the limit is {MAX_PLIES}.",
        )

    comments = [(node.comment or "").strip() for node in game.mainline()]

    board = game.board()
    start_fen = board.fen()

    nodes: list[Node] = []
    for i, move in enumerate(moves):
        report = cct.analyse(board, move)
        nodes.append(
            _node(
                board,
                index=i,
                san=board.san(move),
                uci=move.uci(),
                comment=comments[i] if i < len(comments) else "",
                report=report,
                incoming=moves[i - 1] if i > 0 else None,
            )
        )
        board.push(move)

    nodes.append(
        _node(
            board,
            index=len(moves),
            san=None,
            uci=None,
            comment="",
            report=cct.analyse(board, None),
            incoming=moves[-1] if moves else None,
        )
    )

    return AnalysedGame(
        headers={k: str(v) for k, v in game.headers.items()},
        start_fen=start_fen,
        result=game.headers.get("Result", "*"),
        ply_count=len(moves),
        plies=nodes,
    )


def build_game_response(pgn_text: str | None, game_index: int = 0) -> GameResponse:
    summaries = list_games(pgn_text)
    game = analyse_game(pgn_text, game_index)
    return GameResponse(games=summaries, selected_index=game_index, game=game)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _node(
    board: chess.Board,
    *,
    index: int,
    san: str | None,
    uci: str | None,
    comment: str,
    report,
    incoming: chess.Move | None,
) -> Node:
    last_move = None
    if incoming is not None:
        last_move = {
            "from": chess.square_name(incoming.from_square),
            "to": chess.square_name(incoming.to_square),
        }
    return Node(
        index=index,
        move_number=board.fullmove_number,
        turn="w" if board.turn == chess.WHITE else "b",
        fen=board.fen(),
        san=san,
        uci=uci,
        last_move=last_move,
        comment=comment,
        in_check=board.is_check(),
        is_checkmate=board.is_checkmate(),
        is_stalemate=board.is_stalemate(),
        cct=report,
    )
