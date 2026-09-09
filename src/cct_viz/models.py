"""Pydantic v2 data models (spec section 6).

Every model serialises with the exact JSON keys required by the spec. The
``Candidate`` model uses ``from`` / ``to`` aliases, so callers must serialise
with ``by_alias=True`` (FastAPI's ``jsonable_encoder`` does this by default).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class Gain(BaseModel):
    """A concrete reason a quiet move is a threat (spec 6.1 / 7.3)."""

    kind: Literal["mate", "hanging", "favourable", "fork"]
    score: int
    san: str = ""
    square: str = ""
    targets: list[str] = Field(default_factory=list)
    text: str = ""


class Candidate(BaseModel):
    """One entry in a CCT list (spec 6.2)."""

    model_config = ConfigDict(populate_by_name=True)

    san: str
    uci: str
    from_square: str = Field(alias="from")
    to_square: str = Field(alias="to")
    piece: str
    is_check: bool = False
    is_capture: bool = False
    is_mate: bool = False
    is_promotion: bool = False
    is_en_passant: bool = False
    captured: Optional[str] = None
    played: bool = False
    score: int = 0
    gains: list[Gain] = Field(default_factory=list)


class CctReport(BaseModel):
    """The Checks / Captures / Threats report for one position (spec 6.3)."""

    checks: list[Candidate] = Field(default_factory=list)
    captures: list[Candidate] = Field(default_factory=list)
    threats: list[Candidate] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    truncated: dict[str, bool] = Field(default_factory=dict)


class Node(BaseModel):
    """A position in the game (spec 6.4)."""

    index: int
    move_number: int
    turn: Literal["w", "b"]
    fen: str
    san: Optional[str] = None
    uci: Optional[str] = None
    last_move: Optional[dict] = None
    comment: str = ""
    in_check: bool = False
    is_checkmate: bool = False
    is_stalemate: bool = False
    cct: CctReport


class GameSummary(BaseModel):
    """One row of the ``games`` array in the API response (spec 5.4)."""

    index: int
    white: str
    black: str
    event: str
    site: str
    date: str
    round: str
    result: str
    eco: str
    ply_count: int


class AnalysedGame(BaseModel):
    headers: dict[str, str]
    start_fen: str
    result: str
    ply_count: int
    plies: list[Node]


class GameResponse(BaseModel):
    games: list[GameSummary]
    selected_index: int
    game: AnalysedGame
