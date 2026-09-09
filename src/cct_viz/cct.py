"""The CCT engine (spec section 7).

Given a ``chess.Board`` this module enumerates, for the side to move:

* **Checks** — every legal move that gives check.
* **Captures** — every legal move that captures.
* **Threats** — every legal *quiet* move that creates a new static gain
  (a mate in one, a hanging piece, a favourable capture, or a fork) that the
  mover did not already have.

It is a candidate-move enumerator, not an engine: no search, no SEE, no
evaluation. The rules here are implemented literally as written in the spec so
that the acceptance tests in section 11 reproduce exactly.

``analyse`` never mutates the board it is given: every ``push`` is matched by a
``pop`` and the final state is asserted to be unchanged.
"""

from __future__ import annotations

import chess

from .models import Candidate, CctReport, Gain

VALUE: dict[int, int] = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 100,
}

LETTER_VALUE: dict[str, int] = {"P": 1, "N": 3, "B": 3, "R": 5, "Q": 9, "K": 100}

#: Each CCT list is capped at this many candidates after sorting (spec 7.7).
MAX_LIST = 12


def square_name(square: int) -> str:
    return chess.square_name(square)


def victim_value(board: chess.Board, move: chess.Move) -> int:
    """Value of the piece captured by ``move`` (0 if it is not a capture)."""
    if board.is_en_passant(move):
        return 1
    piece = board.piece_at(move.to_square)
    if piece is None:
        return 0
    return VALUE[piece.piece_type]


def _piece_letter(board: chess.Board, square: int) -> str:
    return chess.piece_symbol(board.piece_at(square).piece_type).upper()


def _gain_text(kind: str, san: str, square: str, targets: list[str]) -> str:
    """Ready-to-display sentence for a gain (spec 7.5) — must match exactly."""
    if kind == "mate":
        return f"threatens mate: {san}"
    if kind == "hanging":
        return f"wins a hanging piece on {square}: {san}"
    if kind == "favourable":
        return f"wins material on {square}: {san}"
    if kind == "fork":
        return f"double attack from {square} on {' and '.join(targets)}"
    return ""


# --------------------------------------------------------------------------- #
# The "gains" primitives (spec 7.3)
# --------------------------------------------------------------------------- #


def find_gains(board: chess.Board) -> dict[int, Gain]:
    """Material the side to move can win right now, keyed by target square."""
    them = not board.turn
    out: dict[int, Gain] = {}
    for move in board.generate_legal_captures():
        victim = victim_value(board, move)
        attacker = VALUE[board.piece_at(move.from_square).piece_type]
        defended = bool(board.attackers(them, move.to_square))
        if not defended:
            kind = "hanging"
        elif victim > attacker:
            kind = "favourable"
        else:
            continue  # even or losing capture: not a gain
        existing = out.get(move.to_square)
        if existing is None or victim > existing.score:
            san = board.san(move)
            name = square_name(move.to_square)
            out[move.to_square] = Gain(
                kind=kind,
                score=victim,
                san=san,
                square=name,
                targets=[],
                text=_gain_text(kind, san, name, []),
            )
    return out


def find_mate_in_one(board: chess.Board) -> chess.Move | None:
    """First legal move that is checkmate, else ``None``.

    Only checking moves are tested — that is the whole performance trick.
    """
    for move in board.legal_moves:
        if board.gives_check(move):
            board.push(move)
            mate = board.is_checkmate()
            board.pop()
            if mate:
                return move
    return None


def find_fork(board: chess.Board, square: int) -> list[tuple[int, str]] | None:
    """Enemy pieces worth >= 3 attacked by the piece standing on ``square``.

    Returns ``[(value, square_name), ...]`` sorted by value descending when at
    least two such pieces are attacked, else ``None``.
    """
    them = not board.turn
    targets: list[tuple[int, str]] = []
    for target in board.attacks(square):
        piece = board.piece_at(target)
        if piece and piece.color == them and VALUE[piece.piece_type] >= 3:
            targets.append((VALUE[piece.piece_type], square_name(target)))
    targets.sort(reverse=True)
    return targets if len(targets) >= 2 else None


# --------------------------------------------------------------------------- #
# Candidate construction
# --------------------------------------------------------------------------- #


def _make_candidate(
    board: chess.Board, move: chess.Move, played: chess.Move | None
) -> Candidate:
    san = board.san(move)
    is_check = board.gives_check(move)
    is_capture = board.is_capture(move)
    is_en_passant = board.is_en_passant(move)

    captured: str | None = None
    if is_capture:
        captured = "P" if is_en_passant else _piece_letter(board, move.to_square)

    is_mate = False
    if is_check:
        board.push(move)
        is_mate = board.is_checkmate()
        board.pop()

    return Candidate(
        san=san,
        uci=move.uci(),
        from_square=square_name(move.from_square),
        to_square=square_name(move.to_square),
        piece=_piece_letter(board, move.from_square),
        is_check=is_check,
        is_capture=is_capture,
        is_mate=is_mate,
        is_promotion=move.promotion is not None,
        is_en_passant=is_en_passant,
        captured=captured,
        played=(played is not None and move == played),
        score=0,
        gains=[],
    )


# --------------------------------------------------------------------------- #
# Truncation (spec 7.7)
# --------------------------------------------------------------------------- #


def _truncate(candidates: list[Candidate]) -> tuple[list[Candidate], int, bool]:
    count = len(candidates)
    if count <= MAX_LIST:
        return candidates, count, False

    kept = candidates[:MAX_LIST]
    if not any(c.played for c in kept):
        played = next((c for c in candidates[MAX_LIST:] if c.played), None)
        if played is not None:
            kept = kept[:-1] + [played]
    return kept, count, True


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def analyse(board: chess.Board, played: chess.Move | None = None) -> CctReport:
    fen_before = board.fen()
    stack_before = len(board.move_stack)

    checks = _find_checks(board, played)
    captures = _find_captures(board, played)
    threats = _find_threats(board, played)

    assert board.fen() == fen_before, "analyse() mutated the board (fen)"
    assert len(board.move_stack) == stack_before, "analyse() mutated the move stack"

    checks_k, checks_n, checks_t = _truncate(checks)
    captures_k, captures_n, captures_t = _truncate(captures)
    threats_k, threats_n, threats_t = _truncate(threats)

    return CctReport(
        checks=checks_k,
        captures=captures_k,
        threats=threats_k,
        counts={"checks": checks_n, "captures": captures_n, "threats": threats_n},
        truncated={"checks": checks_t, "captures": captures_t, "threats": threats_t},
    )


def _find_checks(board: chess.Board, played: chess.Move | None) -> list[Candidate]:
    out: list[Candidate] = []
    for move in board.legal_moves:
        if not board.gives_check(move):
            continue
        candidate = _make_candidate(board, move, played)
        if candidate.is_mate:
            candidate.score = 1000
        elif candidate.is_capture:
            candidate.score = victim_value(board, move)
        else:
            candidate.score = 0
        out.append(candidate)
    out.sort(
        key=lambda c: (
            0 if c.is_mate else 1,
            0 if c.is_capture else 1,
            c.san,
        )
    )
    return out


def _find_captures(board: chess.Board, played: chess.Move | None) -> list[Candidate]:
    out: list[Candidate] = []
    for move in board.legal_moves:
        if not board.is_capture(move):
            continue
        candidate = _make_candidate(board, move, played)
        candidate.score = victim_value(board, move)
        out.append(candidate)
    out.sort(key=lambda c: (-c.score, LETTER_VALUE[c.piece], c.san))
    return out


def _find_threats(board: chess.Board, played: chess.Move | None) -> list[Candidate]:
    baseline = find_gains(board)
    baseline_squares = set(baseline.keys())
    baseline_mate = find_mate_in_one(board) is not None

    out: list[Candidate] = []
    for move in board.legal_moves:
        if board.gives_check(move) or board.is_capture(move):
            continue  # quiet moves only

        candidate = _make_candidate(board, move, played)

        board.push(move)
        board.push(chess.Move.null())  # flip back to the mover

        gains: list[Gain] = [
            gain
            for square, gain in find_gains(board).items()
            if square not in baseline_squares
        ]

        mate = find_mate_in_one(board)
        if mate is not None and not baseline_mate:
            mate_san = board.san(mate)
            gains.append(
                Gain(
                    kind="mate",
                    score=1000,
                    san=mate_san,
                    square=square_name(mate.to_square),
                    targets=[],
                    text=_gain_text("mate", mate_san, "", []),
                )
            )

        fork = find_fork(board, move.to_square)

        board.pop()
        board.pop()

        if fork is not None:
            names = [name for _, name in fork]
            landed = square_name(move.to_square)
            gains.append(
                Gain(
                    kind="fork",
                    score=fork[1][0],  # value of the second target: what you win
                    san="",
                    square=landed,
                    targets=names,
                    text=_gain_text("fork", "", landed, names),
                )
            )

        if gains:
            gains.sort(key=lambda g: (-g.score, g.san))
            candidate.gains = gains[:3]
            candidate.score = candidate.gains[0].score
            out.append(candidate)

    out.sort(key=lambda c: (-c.score, c.san))
    return out
