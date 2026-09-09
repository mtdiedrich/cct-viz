# Spec: Play Mode — play both sides and read CCT for both colours

Version 1.0 · Status: ready to implement · Target: the existing CCT Viz repo

## 0. How to use this document

This is a complete build specification for a second feature in an app that
already exists. Implement it top to bottom. Section 11 contains concrete
acceptance tests with **exact expected values**; every value in it was produced
by running the CCT engine that is already in this repo, so your implementation
must reproduce them exactly.

Section 2 lists what already exists and what you must not break. Read it first.
If something is genuinely ambiguous, pick the simplest option that satisfies
Section 11 and note it in `README.md`.

The existing feature is specified in [`cct-viz-spec.md`](./cct-viz-spec.md).
References below of the form "v1 §7" point at that document.

---

## 1. Product summary

Today the app takes a **PGN** and steps through a finished game, showing the
CCT report **for the side to move** at each ply.

Play Mode adds a second page at `/play` where there is no PGN. The user makes
the moves themselves, **for both colours**, on an interactive board. After every
move — and at every position they rewind to — the page shows **two CCT reports:
one for White and one for Black**.

There is no engine and no opponent. The user is both players. The point of the
feature is the second panel: what the *waiting* side is threatening is exactly
the information a player forgets to check.

### 1.1 Primary user flow

1. User opens `http://127.0.0.1:8000/play`.
2. The board is at the standard start position. Both CCT panels read 0 / 0 / 0.
3. User clicks e2, then e4. The move is played.
4. The Black panel (Black is now to move) shows three threats — `Nf6`, `d5`,
   `f5`, each "wins a hanging piece on e4". The White panel, now the *waiting*
   side, reads 0 / 0 / 0.
5. User keeps playing, for both sides, in the same window.
6. User presses `←`. The board and **both** panels step back one ply.

### 1.2 MUST be delivered

- New page `/play` with a click-to-move chessboard.
- New endpoint `POST /api/play`.
- CCT for **both** colours at every position (Section 3).
- Move list, navigation (start / prev / next / end, click any ply), takeback.
- Start from the standard position or from a user-supplied FEN.
- Copy the played game out as PGN.
- The session survives a page refresh.

### 1.3 Explicitly out of scope

- Any chess engine, evaluation, best-move suggestion, or opponent.
- Variations / branching trees. The line is linear (Section 9.4).
- Accounts, server-side saved games, share links.
- Any change to the v1 feature (Section 2.2).

---

## 2. What already exists

### 2.1 Contracts you will reuse

These have been verified against the current `main`. Reuse them; do not
reimplement them.

**`src/cct_viz/cct.py`** — the CCT engine.

```python
MAX_LIST = 12

def analyse(board: chess.Board, played: chess.Move | None = None) -> CctReport:
    """CCT report for the side to move on `board` (v1 section 7).

    Never mutates `board` — it asserts the FEN and the move stack are
    unchanged before returning. If `played` is given, the candidate equal to
    that move is flagged `played=True`. Each of the three lists is truncated
    to MAX_LIST entries.
    """
```

**`src/cct_viz/models.py`** — Pydantic v2 models `Gain`, `Candidate`,
`CctReport`, `Node`, `GameSummary`, `AnalysedGame`, `GameResponse`.

```python
class CctReport(BaseModel):
    checks: list[Candidate]
    captures: list[Candidate]
    threats: list[Candidate]
    counts: dict[str, int]      # {"checks": N, "captures": N, "threats": N} — pre-truncation
    truncated: dict[str, bool]  # {"checks": bool, "captures": bool, "threats": bool}
```

`Candidate` declares `from_square: str = Field(alias="from")` and
`to_square: str = Field(alias="to")` with `populate_by_name=True`, so responses
**must** serialise with `by_alias=True` (FastAPI's `jsonable_encoder` does this
by default — just return the model from the route and it is handled).

**`src/cct_viz/server.py`** — the FastAPI app.

```python
STATIC = Path(__file__).parent / "static"

app = FastAPI(title="CCT Viz", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

@app.exception_handler(PgnError)
async def _pgn_error_handler(request: Request, exc: PgnError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"error": {"code": exc.code, "message": exc.message}},
    )

@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html", media_type="text/html")
```

Note that the static directory is **`src/cct_viz/static/`**, not a top-level
`static/`. It currently holds `index.html`, `app.js`, `styles.css` and
`example.pgn`.

**`src/cct_viz/pgn.py`** — holds `PgnError(Exception)` with `.code` and
`.message`. Model `PlayError` on it exactly.

### 2.2 MUST NOT break

The v1 test suite (`tests/test_cct.py`, `tests/test_pgn.py`,
`tests/test_api.py` — 19 tests) must still pass **untouched** when you are done.

- `src/cct_viz/cct.py` — **no edits at all**.
- `src/cct_viz/pgn.py` — no edits (add nothing to it; new logic goes in a new
  module).
- The `Node`, `AnalysedGame`, `GameResponse` models — no field added, removed
  or renamed. Play Mode gets its **own** node model (Section 5.2).
- `POST /api/game`, `GET /api/health`, `GET /` — unchanged behaviour.
- `src/cct_viz/static/index.html` and `app.js` — unchanged.
- `src/cct_viz/static/styles.css` — you may **append** rules for new classes,
  but must not change or remove any existing rule.

---

## 3. The core idea: CCT for the side that is *not* to move

`cct.analyse(board)` only ever answers for the side to move, because everything
it enumerates comes from `board.legal_moves`. To get the other side's report,
hand the other side the move:

```python
board.push(chess.Move.null())   # same position, other side to move
report = cct.analyse(board)
board.pop()
```

A null move switches the side to move and clears the en-passant square. That is
exactly right: an en-passant right belongs to the side to move, so the waiting
side must not see one.

### 3.1 The in-check guard — MUST NOT be skipped

**A null move is only legal when the side to move is not in check.**

If the side to move *is* in check, the null-move position is not a legal chess
position — the enemy king stands en prise — and `cct.analyse` will happily
enumerate king captures and return nonsense. This is not hypothetical. Taking
the Scholar's-mate final position
`r1bqkb1r/pppp1Qpp/2n2n2/4p3/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 0 4`, pushing a
null move and calling `analyse` returns:

```
counts   = {"checks": 35, "captures": 5, "threats": 1}
captures = [Qxe8 (score 100), Qxf6 (score 3), ...]
```

Score 100 is `VALUE[chess.KING]`. That candidate is capturing the black king.

So the rule is:

> **If the side to move is in check, the waiting side has no report.**
> Emit `available: false`, `reason: "side_to_move_in_check"`, `report: null`.

This is also the chess-correct answer: the waiting side does not get to plan
anything, because the side to move must deal with the check first.

### 3.2 The rule, complete

For a legal position `B`:

| Colour | Condition | Report |
| --- | --- | --- |
| side to move | always | `cct.analyse(B, played)` |
| waiting side | `B.is_check()` is **False** | push null → `cct.analyse(B)` → pop |
| waiting side | `B.is_check()` is **True** | unavailable, `reason="side_to_move_in_check"` |

`played` is only ever passed for the **side to move**. The waiting side has no
"move actually played", so every candidate in its report has `played: false`.

---

## 4. Architecture

The server stays **stateless**, exactly like `POST /api/game`. The client owns
the game state — a start FEN plus a list of UCI moves — and asks the server to
analyse it.

```
browser (static/play.js)                 server (src/cct_viz/play.py)
  start_fen + moves[]  ── POST /api/play ──▶  replay moves, analyse both sides
  nodes[]              ◀── JSON ──────────    return PlyNode list
```

### 4.1 Why `analyse_from` exists

Analysing **both** sides of one position costs roughly **25–35 ms** (measured
with this engine on typical middlegame positions, python-chess 1.11).
Re-analysing a whole 200-ply line after every move would take about 6 seconds.
Unacceptable.

So `POST /api/play` takes an `analyse_from` index and returns nodes only for
`index >= analyse_from`:

- **User plays a move** → send the full move list with
  `analyse_from = len(moves)` → the server returns exactly **one** node (the new
  tip) → the client appends it locally. Cost: one position.
- **Page load / FEN change / restored session** → `analyse_from = 0` → the
  server returns every node. Cost: the whole line, once.

Navigation (prev / next / jump) is pure client-side array indexing and issues
**no network request at all**.

---

## 5. Backend

### 5.1 New module `src/cct_viz/play.py`

All new chess logic lives here. Mirror the style of `pgn.py`: a module
docstring, an error class, and pure functions.

```python
MAX_PLAY_MOVES = 300


class PlayError(Exception):
    """A user-facing Play Mode problem. ``code`` is one of the spec's codes."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
```

### 5.2 New models — append to `src/cct_viz/models.py`

```python
class SideReport(BaseModel):
    """CCT for one colour at one position (play-mode spec section 3)."""

    color: Literal["w", "b"]
    to_move: bool
    available: bool
    reason: Optional[str] = None       # "side_to_move_in_check" when unavailable
    report: Optional[CctReport] = None # None when unavailable


class LegalMove(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    uci: str
    san: str
    from_square: str = Field(alias="from")
    to_square: str = Field(alias="to")
    promotion: Optional[str] = None    # "q" | "r" | "b" | "n"


class PlyNode(BaseModel):
    """One position in a played line (play-mode spec section 5.3)."""

    index: int                   # 0 = start position
    move_number: int             # board.fullmove_number
    turn: Literal["w", "b"]
    fen: str
    san: Optional[str] = None    # SAN of the move that LED here; None at index 0
    uci: Optional[str] = None
    last_move: Optional[dict] = None   # {"from": "e2", "to": "e4"} or None
    in_check: bool = False
    is_checkmate: bool = False
    is_stalemate: bool = False
    is_game_over: bool = False
    over_reason: Optional[str] = None  # section 5.4
    result: Optional[str] = None       # "1-0" | "0-1" | "1/2-1/2" | None
    legal_moves: list[LegalMove] = Field(default_factory=list)
    cct: dict[str, SideReport]         # exactly two keys: "w" and "b"


class PlayResponse(BaseModel):
    start_fen: str
    moves: list[str]
    ply_count: int
    analyse_from: int
    plies: list[PlyNode]
```

`index`, `move_number`, `turn`, `fen`, `san`, `uci`, `last_move`, `in_check`,
`is_checkmate`, `is_stalemate` are deliberately named and shaped exactly like
the existing `Node` (v1 §6.4), so the frontend helpers behave the same way.

### 5.3 Building one node

```python
def build_node(board, index, san, uci, incoming, played) -> PlyNode:
    """Analyse `board` for both colours and return a PlyNode.

    `san` / `uci` / `incoming` describe the move that led here (None at
    index 0). `played` is the move that will be played FROM here (None at the
    tip). Must not leave `board` mutated.
    """
```

Required work, in order:

1. Record `fen = board.fen()` and `len(board.move_stack)`; assert both are
   unchanged before returning, exactly as `cct.analyse` does.
2. `stm = "w" if board.turn == chess.WHITE else "b"`; `other` is the other one.
3. `cct[stm] = SideReport(color=stm, to_move=True, available=True, reason=None,
   report=cct.analyse(board, played))`.
4. If `board.is_check()`:
   `cct[other] = SideReport(color=other, to_move=False, available=False,
   reason="side_to_move_in_check", report=None)`.
   Otherwise push a null move, call `cct.analyse(board)` with **no** `played`,
   pop, and store it with `available=True, reason=None`.
5. `legal_moves`: iterate `board.legal_moves` and build a `LegalMove` for each.
   Take `board.san(move)` **before** any push. Sort by SAN ascending so the
   output is stable.
6. `last_move` is `{"from": chess.square_name(incoming.from_square), "to":
   chess.square_name(incoming.to_square)}`, or `None`.
7. Game-over fields per Section 5.4.

### 5.4 Game-over detection

Check in this order; stop at the first hit.

| Test | `over_reason` | `result` |
| --- | --- | --- |
| `board.is_checkmate()` | `"checkmate"` | `"1-0"` if Black is to move, else `"0-1"` |
| `board.is_stalemate()` | `"stalemate"` | `"1/2-1/2"` |
| `board.is_insufficient_material()` | `"insufficient_material"` | `"1/2-1/2"` |
| `board.is_seventyfive_moves()` | `"seventyfive_moves"` | `"1/2-1/2"` |
| `board.is_fivefold_repetition()` | `"fivefold_repetition"` | `"1/2-1/2"` |
| none of the above | `None` | `None` |

`is_game_over` is `over_reason is not None`. Only the automatic
(non-claimable) draws are used, so a result never depends on a player claiming
anything.

A checkmated position still produces a valid node: the side to move has an
empty report (no legal moves, so all three lists are empty and all counts are
0) and the waiting side is unavailable, because being mated means being in
check.

### 5.5 Building the line

```python
def build_line(start_fen: str | None, moves: list[str], analyse_from: int) -> PlayResponse:
```

1. **Start position.** If `start_fen` is falsy, `board = chess.Board()`.
   Otherwise `chess.Board(start_fen)`, converting `ValueError` into
   `PlayError("BAD_FEN", ...)`. Then **`if not board.is_valid(): raise
   PlayError("BAD_FEN", ...)`**. That second check rejects positions such as
   `R3k3/8/8/8/8/8/8/4K3 w - - 0 1`, where the side *not* to move is in check —
   which would otherwise poison the very first null move. Record the normalised
   `board.fen()` as the response's `start_fen`.
2. **Length guard.** `len(moves) > MAX_PLAY_MOVES` →
   `PlayError("MOVES_TOO_LONG", ...)`.
3. **Range guard.** `analyse_from` must be an int in `0 .. len(moves)`
   inclusive; otherwise `PlayError("BAD_ANALYSE_FROM", ...)`.
4. **Replay.** Walk `index = 0 .. len(moves)`. The move played from index `i` is
   `moves[i]` if it exists, else `None`. Parse with `chess.Move.from_uci`; a
   malformed string (`ValueError`) or a move not in `board.legal_moves` is
   `PlayError("ILLEGAL_MOVE", ...)`, with a message naming the move and its
   ply, e.g. `Illegal move 'e2e5' at ply 0.` Take `board.san(move)` **before**
   pushing.
5. **Analyse selectively.** Call `build_node` only when `index >=
   analyse_from`. For skipped indices, still replay the move — you need the
   board — but do no analysis. That is the whole point of `analyse_from`.
6. Return `PlayResponse(start_fen=..., moves=moves, ply_count=len(moves),
   analyse_from=analyse_from, plies=[...])`.

A line has `len(moves) + 1` positions, so `analyse_from == len(moves)` returns
exactly one node — the tip.

### 5.6 Optional: memoisation

You **may** wrap the both-sides analysis in a `functools.lru_cache`
(maxsize around 512) keyed by `(fen, played_uci_or_None)`, which makes a full
`analyse_from=0` refetch nearly free on a line already played. This is a
nicety, not a requirement, and it must not change any output. If you add it,
cache raw data rather than Pydantic models, or make sure nothing mutates a
cached model.

---

## 6. API

### 6.1 `POST /api/play`

Request body (`PlayRequest`, declared in `server.py` alongside `GameRequest`):

```json
{
  "start_fen": null,
  "moves": ["e2e4", "e7e5"],
  "analyse_from": 2
}
```

- `start_fen`: `str | None = None`. Null / omitted / empty = standard start.
- `moves`: `list[str] = []`, UCI. Promotions are five characters (`"e7e8q"`).
- `analyse_from`: `int = 0`.

Response `200`:

```json
{
  "start_fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
  "moves": ["e2e4", "e7e5"],
  "ply_count": 2,
  "analyse_from": 2,
  "plies": [
    {
      "index": 2,
      "move_number": 2,
      "turn": "w",
      "fen": "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2",
      "san": "e5",
      "uci": "e7e5",
      "last_move": {"from": "e7", "to": "e5"},
      "in_check": false,
      "is_checkmate": false,
      "is_stalemate": false,
      "is_game_over": false,
      "over_reason": null,
      "result": null,
      "legal_moves": [
        {"uci": "a2a3", "san": "a3", "from": "a2", "to": "a3", "promotion": null}
      ],
      "cct": {
        "w": {
          "color": "w", "to_move": true, "available": true, "reason": null,
          "report": {
            "checks": [], "captures": [], "threats": [],
            "counts": {"checks": 0, "captures": 0, "threats": 0},
            "truncated": {"checks": false, "captures": false, "threats": false}
          }
        },
        "b": {
          "color": "b", "to_move": false, "available": true, "reason": null,
          "report": { "...": "same shape" }
        }
      }
    }
  ]
}
```

Register a `PlayError` handler alongside the existing `PgnError` one, producing
the identical envelope:

```python
@app.exception_handler(PlayError)
async def _play_error_handler(request: Request, exc: PlayError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"error": {"code": exc.code, "message": exc.message}},
    )
```

### 6.2 `GET /play`

```python
@app.get("/play")
def play_page() -> FileResponse:
    return FileResponse(STATIC / "play.html", media_type="text/html")
```

---

## 7. Errors

All failures are **HTTP 400** with the same envelope v1 uses:

```json
{"error": {"code": "ILLEGAL_MOVE", "message": "Illegal move 'e2e5' at ply 0."}}
```

| Code | Raised when |
| --- | --- |
| `BAD_FEN` | `start_fen` will not parse, or parses to a position `board.is_valid()` rejects |
| `MOVES_TOO_LONG` | `len(moves) > 300` |
| `BAD_ANALYSE_FROM` | `analyse_from` is not an int in `0 .. len(moves)` |
| `ILLEGAL_MOVE` | a UCI string is malformed, or the move is not legal in its position |

Messages are user-facing — the frontend shows them verbatim. Do not leak stack
traces.

---

## 8. Frontend — structure

Three new files in the existing static directory:

- `src/cct_viz/static/play.html`
- `src/cct_viz/static/play.css`
- `src/cct_viz/static/play.js`

`play.html` links **both** stylesheets — `/static/styles.css` first, then
`/static/play.css` — so the board, panels and candidate rows inherit the v1
look and `play.css` only adds what is new. No build step, no framework, no CDN;
a single classic `<script src="/static/play.js">`, matching `index.html`.

`index.html` is frozen (Section 2.2), so do **not** add a link to `/play` from
it. Navigation goes one way: `play.html`'s header carries a link back to `/`.

### 8.1 Reuse these helpers from `app.js`

`play.js` is a separate file and may not import from `app.js` (it is not a
module). **Copy** these functions across verbatim; do not rewrite them, and do
not "improve" their output, or Section 11's expected strings will drift:

| Helper | Why |
| --- | --- |
| `PIECE_GLYPH`, `PIECE_WORD` | identical piece rendering and wording |
| `parseFenBoard(fen)` | FEN placement → `{squareName: pieceChar}` |
| `markSquare(name, cls)` / `clearMarks(cls)` | square highlighting |
| `coord(kind, text)` | file/rank labels on the board edge |
| `captureWord(c)`, `checkWord(c)`, `threatWord(c)` | candidate detail text |
| `strengthPx(c)` | the score bar width |

`threatWord` already renders `gains[0].text` verbatim (plus `(+N more)`). The
engine pre-formats those sentences — `wins a hanging piece on e4: Nxe4`,
`double attack from d3 on b3 and c4`, `threatens mate: Qxf7#`. **Never
re-derive them in the frontend.**

### 8.2 Layout

```
+--------------------------------------------------------------------+
|  CCT Viz - Play        [New game] [FEN...] [Flip] [Copy PGN]  [PGN mode] |
+----------------------+---------------------------------------------+
|                      |  White - to move              C2  P4  T1    |
|      chessboard      |    Checks    ...                            |
|         8 x 8        |    Captures  ...                            |
|                      |    Threats   ...                            |
|                      +---------------------------------------------+
|                      |  Black - waiting              C0  P2  T5    |
|  [|<] [<] [>] [>|]   |    Checks    ...                            |
|   [Takeback] [Flip]  |    Captures  ...                            |
+----------------------+    Threats   ...                            |
|  move list           |                                             |
|  1. e4 e5            |                                             |
|  2. Bc4 Nc6  <- here |                                             |
+----------------------+---------------------------------------------+
             status bar: "Black to move - 0 checks, 2 captures, 5 threats"
```

Below 900 px wide, stack: board, then the two CCT panels, then the move list.
The board must stay square and must never overflow.

### 8.3 DOM contract

Board markup matches v1 exactly, with one change: squares must be interactive.
Keep the `div.sq` element and classes so `styles.css` applies, and add
`role="button"` and `tabindex="0"` so they are clickable and keyboard-reachable.

```html
<div id="board">
  <div class="sq light" data-square="a8" role="button" tabindex="0"
       aria-label="a8, black rook"><span class="piece black">♜</span></div>
  ...
</div>
```

| Selector | What it is |
| --- | --- |
| `#board .sq[data-square="e4"]` | one square; classes `light` / `dark` as in v1 |
| `.sq .piece.white` / `.piece.black` | the glyph, as in v1 |
| `.sq.hl-last` | the two squares of the move that led here (v1 class) |
| `.sq.hl-cand-from`, `.sq.hl-cand-to`, `.sq.hl-gain` | CCT row highlight (v1 classes) |
| `.sq.hl-sel` | **new** — the selected origin square |
| `.sq.hl-dest` | **new** — a legal destination for the selected origin |
| `.sq.hl-check` | **new** — the king square when `in_check` |
| `#panel-w`, `#panel-b` | the White / Black CCT panels; `.to-move` when that side is to move |
| `#panel-w .cct-section[data-kind="checks"]` | one of the three sections (`checks`, `captures`, `threats`) |
| `.candidate-list` | the `<ul>` inside a section (v1 class) |
| `.candidate-list li` | one candidate: `<li tabindex="0">` with `.san-chip`, `.cand-detail`, `.cand-bar`, and `.played` when applicable — identical to v1's `candidateRow` |
| `.cct-truncated` | the "showing 12 of 27" line |
| `.cct-unavailable` | the message shown when a side has no report |
| `#moves` | move list; cells `.move[data-index="7"]`, `.move.current` |
| `#nav-start`, `#nav-prev`, `#nav-next`, `#nav-end`, `#nav-flip` | as in v1 |
| `#takeback` | **new** |
| `#btn-new`, `#btn-fen`, `#btn-pgn` | toolbar |
| `#status` | status bar, with `role="status" aria-live="polite"` |
| `#play-error` | error banner, reusing v1's `.error-banner` class |

### 8.4 The two CCT panels

Each panel header shows the colour, whether it is **to move** or **waiting**,
and three count badges. Each section renders its candidates in the order the
server sent them — **do not re-sort**. The ordering is part of the CCT engine's
contract (v1 §7) and Section 11 asserts it.

- If `report.truncated[kind]` is true, show
  `showing {report[kind].length} of {report.counts[kind]}` in `.cct-truncated`.
- If `available` is false, the panel body is a single `.cct-unavailable`
  message: **"No plan for White — Black is to move and in check."** (with the
  colours filled in correctly).
- An empty list renders a muted em dash, as v1 does.

### 8.5 Panel order

White's panel is always on top and Black's below, regardless of board
orientation or whose turn it is. A panel that moves around is harder to read
than one that is labelled; the header already says who is to move. Give the
to-move panel a visible accent via `#panel-w.to-move` / `#panel-b.to-move`.

---

## 9. Frontend — behaviour

### 9.1 Client state

```js
const state = {
  startFen: null,   // null = standard start
  moves: [],        // UCI strings
  nodes: [],        // PlyNode[]; nodes[i].index === i
  cursor: 0,        // which node is displayed
  flipped: false,   // same name as v1
  selected: null,   // selected origin square name, or null
  pinned: null,     // {uci, color} of a pinned CCT highlight, or null
};
```

Invariant: `state.nodes.length === state.moves.length + 1`.

### 9.2 Making a move

1. Click a square holding a piece of the side to move → it gets `.hl-sel` and
   every legal destination gets `.hl-dest`. Derive both by filtering
   `node.legal_moves` on `from` — the client never decides legality itself.
   Clicking the same square deselects; clicking another of your own pieces
   re-selects.
2. Click a `.hl-dest` square → if that `from`/`to` pair matches more than one
   legal move (a promotion), open a chooser with queen / rook / bishop / knight
   and use the chosen entry's `uci`. Otherwise use the single match.
3. Append the uci to `state.moves`, `POST /api/play` with
   `analyse_from = state.moves.length`, append the single returned node, set
   `cursor = nodes.length - 1`, re-render.
4. On error: **roll back** `state.moves`, leave the board as it was, and show
   `error.message` in `#play-error`.

Click-to-move is required and must work from the keyboard (squares are
`role="button" tabindex="0"`; Enter and Space activate them). Drag-and-drop is
optional.

Moves are accepted only when `cursor === nodes.length - 1` (see Section 9.4),
and are rejected outright when the current node has `is_game_over` — show the
result in `#status` and stop.

### 9.3 Playing a move from a CCT row

- **Hover** (or focus) a candidate `<li>` → highlight its squares using v1's
  `highlightCandidate` behaviour: `hl-cand-from`, `hl-cand-to`, and for threats
  `hl-gain` on `gains[0].square` and each of `gains[0].targets`. This works for
  **both** panels — putting the waiting side's ideas on the board is the point
  of the feature.
- **Click** a candidate:
  - if it belongs to the side to move **and** the cursor is at the tip → play
    that move (same path as Section 9.2);
  - otherwise → pin / unpin the highlight so it survives the pointer leaving.

### 9.4 Navigation and truncation

`#nav-start` / `#nav-prev` / `#nav-next` / `#nav-end` and clicking a `.move`
set `state.cursor`. These are local — **no fetch**. Keyboard, matching v1:
`←` prev, `→` next, `Home` start, `End` end, `f` flip, plus `u` takeback.
Ignore these while focus is in a text input or textarea.

If the user makes a move while `cursor < nodes.length - 1`, the line is
**truncated**: drop everything in `moves` and `nodes` after the cursor, then
apply the new move. Show `Line truncated at ply N.` in `#status`. There are no
variations.

`#takeback` drops the last move (`moves.pop()`, `nodes.pop()`,
`cursor = nodes.length - 1`) and needs no fetch. Disabled when
`moves.length === 0`.

### 9.5 New game / FEN

- `#btn-new` → confirm if `moves.length > 0`, then reset to `startFen: null`,
  `moves: []`, and fetch with `analyse_from = 0`.
- `#btn-fen` → prompt for a FEN, set `startFen`, clear `moves`, fetch with
  `analyse_from = 0`. On `BAD_FEN`, show the message and keep the current game.

### 9.6 Persistence

After every change, persist `{startFen, moves, cursor, flipped}` — **not**
`nodes` — to `localStorage` under `cctviz.play.v1`. On load, if the key parses,
restore it and fetch with `analyse_from = 0`. If that request fails for any
reason, clear the key and start a fresh game. A bad saved state must never
brick the page.

### 9.7 Copy PGN

`#btn-pgn` builds PGN **client-side** from the nodes and copies it to the
clipboard (`navigator.clipboard.writeText`, with a hidden `<textarea>` +
`select()` + `execCommand("copy")` fallback), then confirms in `#status`.

```
[Event "CCT Viz Play"]
[Site "CCT Viz"]
[Date "2026.09.09"]
[Round "-"]
[White "Player"]
[Black "Player"]
[Result "*"]
```

`Result` is the last node's `result`, or `"*"` when it is `null`. If `startFen`
is set and is not the standard start position, also emit `[SetUp "1"]` and
`[FEN "..."]`.

Movetext comes from `nodes[1..]`: each node carries the `san` of the move that
reached it, and the `move_number` / `turn` of the position that move produced.
Emit `N.` before a White move, and `N...` before a Black move that opens the
movetext (needed when a FEN game starts with Black to move). Wrap at 80 columns
and end with the result token.

The output must be loadable by the v1 page — that is Section 11.9 item 6.

### 9.8 Status bar and accessibility

After each render `#status` reads
`"{Colour} to move — {n} checks, {n} captures, {n} threats"`, using the
**pre-truncation** `counts` of the side to move. On game over it reads the
result and reason instead. Panels are `<section>` elements with
`aria-labelledby` pointing at their header; candidate lists are `<ul>`; the
board carries `aria-label="chess board"` as in v1.

---

## 10. Performance

- `POST /api/play` with `analyse_from == len(moves)` MUST analyse exactly one
  position. On a 60-ply line such a request must complete well under 200 ms.
- Navigation MUST issue no network request.
- Re-rendering the board on navigation must not flicker; rebuilding the 64
  squares as v1's `renderBoard` does is acceptable.

---

## 11. Acceptance tests

Put these in a **new** file `tests/test_play.py`, using FastAPI's `TestClient`
as `tests/test_api.py` does. Every value below was produced by running the CCT
engine currently in this repo. They are exact, not illustrative.

### 11.1 Start position — both sides quiet

`POST /api/play` with `{"moves": [], "analyse_from": 0}`:

- one node; `index == 0`, `turn == "w"`, `move_number == 1`, `san is None`,
  `last_move is None`, `is_game_over is False`.
- `len(legal_moves) == 20`.
- `cct["w"]["to_move"] is True`, `cct["b"]["to_move"] is False`.
- **both** sides `available is True`, with
  `counts == {"checks": 0, "captures": 0, "threats": 0}` and all three lists
  empty.

### 11.2 After 1.e4 — the waiting side is the interesting one

`{"moves": ["e2e4"], "analyse_from": 0}` → two nodes. On `plies[1]`
(`turn == "b"`, `san == "e4"`, `last_move == {"from": "e2", "to": "e4"}`):

- **Black (to move)**: `counts == {"checks": 0, "captures": 0, "threats": 3}`;
  threat SANs in order `["Nf6", "d5", "f5"]`; each `score == 1`; and
  `gains[0]["text"]` respectively
  `"wins a hanging piece on e4: Nxe4"`,
  `"wins a hanging piece on e4: dxe4"`,
  `"wins a hanging piece on e4: fxe4"`.
- **White (waiting)**: `available is True`,
  `counts == {"checks": 0, "captures": 0, "threats": 0}`.

### 11.3 Scholar's mate — the in-check guard

`{"moves": ["e2e4","e7e5","f1c4","b8c6","d1h5","g8f6","h5f7"],
"analyse_from": 0}` → 8 nodes. On `plies[7]`, whose fen is
`r1bqkb1r/pppp1Qpp/2n2n2/4p3/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 0 4`:

- `turn == "b"`, `in_check is True`, `is_checkmate is True`,
  `is_game_over is True`, `over_reason == "checkmate"`, `result == "1-0"`,
  `legal_moves == []`.
- `cct["b"]`: `available is True`, all three lists empty,
  `counts == {"checks": 0, "captures": 0, "threats": 0}`.
- `cct["w"]`: `available is False`, `report is None`,
  `reason == "side_to_move_in_check"`.

This test is the whole point of Section 3.1 — **it must fail if the guard is
removed.** Without the guard White comes back with 35 checks and a `Qxe8`
capture scoring 100.

### 11.4 The `played` flag

The same move list as 11.3 but `{"analyse_from": 6}`. The response's `plies`
has length 1 and `plies[0]["index"] == 6` — the position before `Qxf7#`, White
to move.

- `cct["w"]["report"]["checks"]` SANs in order `["Qxf7#", "Bxf7+", "Qxe5+"]`,
  with `played` `[True, False, False]`.
- `cct["w"]["report"]["captures"]` SANs in order
  `["Bxf7+", "Qxe5+", "Qxf7#", "Qxh7"]`, with `played` true only on `Qxf7#`.
- `cct["b"]` (waiting): `available is True`,
  `counts == {"checks": 0, "captures": 2, "threats": 5}`, and **no** candidate
  anywhere in it has `played` true.

### 11.5 Starting from a FEN — both sides busy

`{"start_fen": "rn1qkb1r/ppp2ppp/5n2/4p3/2B1P3/1Q6/PPP2PPP/RNB1K2R b KQkq - 3 7",
"moves": [], "analyse_from": 0}` → one node, `turn == "b"`,
`move_number == 7`.

- **Black (to move)**: `counts == {"checks": 3, "captures": 1, "threats": 2}`;
  checks in order `["Bb4+", "Qd1+", "Qd2+"]`; captures `["Nxe4"]`; threats
  `["Qd3", "b5"]`, both `score == 3`, with `gains[0]["text"]`
  `"double attack from d3 on b3 and c4"` and `"wins material on c4: bxc4"`.
- **White (waiting)**: `available is True`,
  `counts == {"checks": 4, "captures": 2, "threats": 4}`; checks in order
  `["Bxf7+", "Bb5+", "Qa4+", "Qb5+"]`; threats in order
  `["Bf4", "Qc3", "Qg3", "f4"]`.

### 11.6 Errors

Each returns HTTP 400 with the given `error.code`.

| Request | `error.code` |
| --- | --- |
| `{"moves": ["e2e5"]}` | `ILLEGAL_MOVE` |
| `{"moves": ["zzzz"]}` | `ILLEGAL_MOVE` |
| `{"start_fen": "not a fen"}` | `BAD_FEN` |
| `{"start_fen": "R3k3/8/8/8/8/8/8/4K3 w - - 0 1"}` | `BAD_FEN` (side not to move is in check) |
| `{"moves": ["e2e4"], "analyse_from": 5}` | `BAD_ANALYSE_FROM` |
| `{"moves": ["e2e4"], "analyse_from": -1}` | `BAD_ANALYSE_FROM` |
| 301 moves | `MOVES_TOO_LONG` |

### 11.7 Purity

`build_node` must not mutate the board it is given. Add an explicit test that
calls `build_node` on a `chess.Board()` and asserts `board.fen()` and
`len(board.move_stack)` are unchanged afterwards — the null-move push/pop is
the easiest thing in this feature to get wrong.

### 11.8 Regression

`python -m pytest` passes: the 19 v1 tests, untouched, plus the new ones.
`GET /` still returns the v1 page; `GET /play` returns the new one; both with
`content-type: text/html`.

### 11.9 Manual UI checklist

1. Open `/play`. Both panels read 0 / 0 / 0; White's panel is marked *to move*.
2. Play `1.e4`. Black's panel shows the three threats; hovering `Nf6` lights up
   g8 and f6, and e4 as the gain square. White's panel reads 0 / 0 / 0 and is
   marked *waiting*.
3. Play `1...e5 2.Bc4 Nc6 3.Qh5 Nf6 4.Qxf7#`, making the last move by clicking
   `Qxf7#` in White's Checks list. `#status` announces mate; White's panel
   shows the unavailable message; the board rejects further input.
4. Press `←` five times: board and **both** panels track the position, with no
   network requests (check the network tab).
5. Press `u` at the tip, then play a different move; the move list truncates
   and `#status` says so.
6. `Copy PGN`, then paste the result into the v1 page at `/` — it loads and
   analyses.
7. Reload `/play`: the game is still there.
8. Resize to 400 px wide: the board stays square, the panels stack, nothing
   overflows horizontally.

---

## 12. Definition of done

- [ ] `src/cct_viz/play.py` with `MAX_PLAY_MOVES`, `PlayError`, `build_node`,
      `build_line`.
- [ ] `SideReport`, `LegalMove`, `PlyNode`, `PlayResponse` appended to
      `src/cct_viz/models.py`; existing models untouched.
- [ ] `POST /api/play`, `GET /play` and the `PlayError` handler in
      `src/cct_viz/server.py`.
- [ ] `src/cct_viz/static/play.html`, `play.css`, `play.js`.
- [ ] `tests/test_play.py` covering 11.1 – 11.7, all green.
- [ ] The 19 v1 tests still green and unmodified.
- [ ] `README.md` gains a short **Play Mode** section (what `/play` is, and the
      in-check rule from Section 3.1).
- [ ] Section 11.9 walked through by hand.
