"""Play Mode: analyse a user-played line for both colours (play-mode spec).

Rules, mirroring the style of :mod:`cct_viz.pgn`:

* The server is stateless. The client owns the line (a start FEN plus a list of
  UCI moves) and asks this module to analyse it.
* Every position gets **two** CCT reports — one for White, one for Black. The
  side to move is analysed directly; the waiting side is analysed by pushing a
  null move (play-mode spec section 3).
* A null move is only legal when the side to move is not in check, so when the
  position is a check the waiting side has no report at all (section 3.1).
* ``build_node`` never mutates the board it is given: the null-move push is
  matched by a pop and the final state is asserted unchanged.
"""

from __future__ import annotations

import chess

from . import cct
from .models import CctReport, LegalMove, PlayResponse, PlyNode, SideReport

#: A played line may not exceed this many moves (play-mode spec section 5.1).
MAX_PLAY_MOVES = 300


class PlayError(Exception):
    """A user-facing Play Mode problem. ``code`` is one of the spec's codes."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# --------------------------------------------------------------------------- #
# Game-over detection (play-mode spec section 5.4)
# --------------------------------------------------------------------------- #


def _game_over(board: chess.Board) -> tuple[str | None, str | None]:
    """Return ``(over_reason, result)``; ``(None, None)`` when the game is on."""
    if board.is_checkmate():
        # The side to move is mated, so the *other* side delivered mate.
        result = "1-0" if board.turn == chess.BLACK else "0-1"
        return "checkmate", result
    if board.is_stalemate():
        return "stalemate", "1/2-1/2"
    if board.is_insufficient_material():
        return "insufficient_material", "1/2-1/2"
    if board.is_seventyfive_moves():
        return "seventyfive_moves", "1/2-1/2"
    if board.is_fivefold_repetition():
        return "fivefold_repetition", "1/2-1/2"
    return None, None


# --------------------------------------------------------------------------- #
# One node (play-mode spec section 5.3)
# --------------------------------------------------------------------------- #


def _legal_moves(board: chess.Board) -> list[LegalMove]:
    out: list[LegalMove] = []
    for move in board.legal_moves:
        san = board.san(move)  # before any push
        out.append(
            LegalMove(
                uci=move.uci(),
                san=san,
                from_square=chess.square_name(move.from_square),
                to_square=chess.square_name(move.to_square),
                promotion=chess.piece_symbol(move.promotion) if move.promotion else None,
            )
        )
    out.sort(key=lambda m: m.san)
    return out


def _waiting_report(board: chess.Board) -> CctReport:
    """CCT for the waiting side: push a null move, analyse, pop."""
    board.push(chess.Move.null())
    try:
        return cct.analyse(board)
    finally:
        board.pop()


def build_node(
    board: chess.Board,
    index: int,
    san: str | None,
    uci: str | None,
    incoming: chess.Move | None,
    played: chess.Move | None,
) -> PlyNode:
    """Analyse ``board`` for both colours and return a :class:`PlyNode`.

    ``san`` / ``uci`` / ``incoming`` describe the move that led here (``None``
    at index 0). ``played`` is the move that will be played FROM here (``None``
    at the tip). Must not leave ``board`` mutated.
    """
    fen_before = board.fen()
    stack_before = len(board.move_stack)

    stm = "w" if board.turn == chess.WHITE else "b"
    other = "b" if stm == "w" else "w"

    cct_reports: dict[str, SideReport] = {}
    cct_reports[stm] = SideReport(
        color=stm,
        to_move=True,
        available=True,
        reason=None,
        report=cct.analyse(board, played),
    )

    if board.is_check():
        cct_reports[other] = SideReport(
            color=other,
            to_move=False,
            available=False,
            reason="side_to_move_in_check",
            report=None,
        )
    else:
        cct_reports[other] = SideReport(
            color=other,
            to_move=False,
            available=True,
            reason=None,
            report=_waiting_report(board),
        )

    last_move = None
    if incoming is not None:
        last_move = {
            "from": chess.square_name(incoming.from_square),
            "to": chess.square_name(incoming.to_square),
        }

    over_reason, result = _game_over(board)

    node = PlyNode(
        index=index,
        move_number=board.fullmove_number,
        turn=stm,
        fen=board.fen(),
        san=san,
        uci=uci,
        last_move=last_move,
        in_check=board.is_check(),
        is_checkmate=board.is_checkmate(),
        is_stalemate=board.is_stalemate(),
        is_game_over=over_reason is not None,
        over_reason=over_reason,
        result=result,
        legal_moves=_legal_moves(board),
        cct=cct_reports,
    )

    assert board.fen() == fen_before, "build_node() mutated the board (fen)"
    assert len(board.move_stack) == stack_before, "build_node() mutated the move stack"
    return node


# --------------------------------------------------------------------------- #
# The whole line (play-mode spec section 5.5)
# --------------------------------------------------------------------------- #


def _start_board(start_fen: str | None) -> chess.Board:
    if not start_fen:
        return chess.Board()
    try:
        board = chess.Board(start_fen)
    except ValueError as exc:
        raise PlayError("BAD_FEN", f"Could not parse FEN: {start_fen!r}.") from exc
    if not board.is_valid():
        raise PlayError("BAD_FEN", f"FEN is not a legal position: {start_fen!r}.")
    return board


def build_line(
    start_fen: str | None, moves: list[str], analyse_from: int
) -> PlayResponse:
    board = _start_board(start_fen)
    normalised_start = board.fen()

    if len(moves) > MAX_PLAY_MOVES:
        raise PlayError(
            "MOVES_TOO_LONG",
            f"A line may not exceed {MAX_PLAY_MOVES} moves; got {len(moves)}.",
        )

    if not isinstance(analyse_from, int) or isinstance(analyse_from, bool):
        raise PlayError("BAD_ANALYSE_FROM", "analyse_from must be an integer.")
    if not 0 <= analyse_from <= len(moves):
        raise PlayError(
            "BAD_ANALYSE_FROM",
            f"analyse_from must be in 0..{len(moves)}; got {analyse_from}.",
        )

    plies: list[PlyNode] = []
    incoming: chess.Move | None = None
    san: str | None = None
    uci: str | None = None

    for index in range(len(moves) + 1):
        played: chess.Move | None = None
        if index < len(moves):
            raw = moves[index]
            try:
                played = chess.Move.from_uci(raw)
            except ValueError:
                played = None
            if played is None or played not in board.legal_moves:
                raise PlayError(
                    "ILLEGAL_MOVE", f"Illegal move {raw!r} at ply {index}."
                )

        # Analyse every index >= analyse_from. The tip (index == len(moves)) is
        # only wanted on a full refetch (analyse_from == 0) or when it is the
        # sole requested node (analyse_from == len(moves)); a mid-line
        # analyse_from asks for the "move" positions only (play-mode spec 4.1,
        # 11.4).
        want = index >= analyse_from
        if index == len(moves) and not (analyse_from == 0 or analyse_from == len(moves)):
            want = False
        if want:
            plies.append(build_node(board, index, san, uci, incoming, played))

        if played is not None:
            san = board.san(played)  # before pushing
            uci = played.uci()
            board.push(played)
            incoming = played

    return PlayResponse(
        start_fen=normalised_start,
        moves=moves,
        ply_count=len(moves),
        analyse_from=analyse_from,
        plies=plies,
    )
