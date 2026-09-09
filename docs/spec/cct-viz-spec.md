# Spec: CCT Viz — PGN step-through with Checks / Captures / Threats

Version 1.0 · Status: ready to implement · Target: a fresh, empty repository

## 0. How to use this document

This is a complete build specification. Implement it top to bottom. Every section
labelled **MUST** is required for the build to be considered done. Do not invent
extra features; do not skip sections. Section 11 contains concrete acceptance
tests with exact expected values — your implementation must reproduce them.

If something is genuinely ambiguous, pick the simplest option that satisfies the
acceptance tests in Section 11 and write a note in `README.md`.

---

## 1. Product summary

A local web application. The user pastes (or uploads) a PGN chess game. The app
parses the game and lets the user step through it one half-move at a time. At
every position it displays the **CCT report** for the side to move:

- **C — Checks:** every legal move that gives check.
- **C — Captures:** every legal move that captures a piece.
- **T — Threats:** every legal quiet move (not a check, not a capture) that
  creates a *new* threat to win material or to mate next move.

CCT is a well-known human tactical-scanning heuristic (list the forcing moves
before you decide). This app is a **candidate-move enumerator**, not a chess
engine. It does no search and gives no evaluation. Say so in the UI (Section 9.7).

### 1.1 Primary user flow

1. User opens `http://127.0.0.1:8000/`.
2. User pastes PGN into a textarea and clicks **Load game**.
3. The app shows a chessboard at the starting position, a move list, and the CCT
   report for White at move 1.
4. User presses `→` (or clicks **Next**). The board advances one half-move; the
   move list highlights the new move; the CCT panel refreshes for the new
   position.
5. The candidate in the CCT lists that equals the move actually played in the
   game is badged **played**.

---

## 2. Glossary (use these words exactly)

| Term | Meaning |
|---|---|
| **ply** | One half-move. `1.e4 e5` is two plies. |
| **node** | A position in the game. A game with *N* plies has *N+1* nodes, indexed `0 .. N`. Node 0 is the start position. |
| **ply index** | The index of the node currently displayed, `0 .. N`. Node `i` is the position *before* ply `i` is played. |
| **mover** | The side to move at the current node. The CCT report is always about the mover. |
| **candidate** | One entry in a CCT list — a single legal move plus metadata. |
| **gain** | A concrete reason a threat move is a threat (a mate, a hanging piece, a favourable capture, or a fork). |
| **quiet move** | A legal move that is neither a check nor a capture. |
| **SAN** | Standard Algebraic Notation, e.g. `Qxf7#`. Produced by `python-chess`. |
| **UCI** | Long algebraic, e.g. `f1c4`. Produced by `python-chess`. |

---

## 3. Technology (MUST use exactly this)

- Python **3.11+**
- [`chess`](https://pypi.org/project/chess/) (python-chess) **>= 1.10** — all
  chess rules, PGN parsing, SAN, FEN. Never hand-roll chess logic.
- [`fastapi`](https://pypi.org/project/fastapi/) **>= 0.110**
- [`pydantic`](https://pypi.org/project/pydantic/) **>= 2.6**
- [`uvicorn[standard]`](https://pypi.org/project/uvicorn/) **>= 0.27**
- Dev only: `pytest >= 8`, `httpx >= 0.27` (for `fastapi.testclient.TestClient`)

Frontend: **plain HTML + CSS + vanilla JavaScript (ES2020), no build step, no
npm, no CDN, no external fonts, no framework.** Everything must work offline.
Chess pieces are rendered as Unicode glyphs, not images.

---

## 4. Repository layout (MUST match)

```
pyproject.toml
README.md
docs/spec/cct-viz-spec.md          <- this file
src/cct_viz/__init__.py            <- __version__ = "0.1.0"
src/cct_viz/__main__.py            <- `python -m cct_viz` starts the server
src/cct_viz/models.py              <- pydantic models (Section 6)
src/cct_viz/cct.py                 <- CCT engine (Section 7)
src/cct_viz/pgn.py                 <- PGN parsing + game analysis (Section 8)
src/cct_viz/server.py              <- FastAPI app (Section 5)
src/cct_viz/static/index.html
src/cct_viz/static/styles.css
src/cct_viz/static/app.js
src/cct_viz/static/example.pgn     <- the Opera Game (Section 9.2)
tests/test_cct.py
tests/test_pgn.py
tests/test_api.py
```

`pyproject.toml` MUST use a src-layout setuptools config so `pip install -e .`
works, and MUST include the `static/` directory as package data.

### 4.1 Commands that MUST work after implementation

```bash
pip install -e ".[dev]"
pytest -q
python -m cct_viz          # serves on http://127.0.0.1:8000
```

`python -m cct_viz` accepts optional `--host` (default `127.0.0.1`) and
`--port` (default `8000`).

---

## 5. HTTP API

The FastAPI app serves both the API and the static frontend. One process, same
origin, therefore **no CORS configuration is needed**.

### 5.1 `GET /`

Returns `src/cct_viz/static/index.html` with `Content-Type: text/html`.

### 5.2 `GET /static/*`

Static files, mounted via `StaticFiles`.

### 5.3 `GET /api/health`

`200` → `{"status": "ok", "version": "0.1.0"}`

### 5.4 `POST /api/game`  ← the only real endpoint

**Request body**

```json
{ "pgn": "<full PGN text>", "game_index": 0 }
```

`game_index` is optional, defaults to `0`.

**Response `200`** — shape defined in Section 6.

```json
{
  "games": [
    { "index": 0, "white": "Paul Morphy", "black": "Duke Karl / Count Isouard",
      "event": "Paris", "site": "Paris FRA", "date": "1858.??.??",
      "round": "?", "result": "1-0", "eco": "", "ply_count": 33 }
  ],
  "selected_index": 0,
  "game": {
    "headers": { "White": "Paul Morphy", "...": "..." },
    "start_fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
    "result": "1-0",
    "ply_count": 33,
    "plies": [ /* ply_count + 1 Node objects, Section 6.4 */ ]
  }
}
```

The endpoint is **stateless**. The client keeps the PGN text in memory and
re-POSTs it with a different `game_index` when the user picks another game from
a multi-game PGN.

**Errors** — always HTTP `400` with this body shape:

```json
{ "error": { "code": "PGN_PARSE_ERROR", "message": "human readable text" } }
```

| `code` | When |
|---|---|
| `PGN_EMPTY` | `pgn` is missing, empty, or whitespace only |
| `PGN_NO_GAMES` | text parsed but contained zero games |
| `PGN_PARSE_ERROR` | python-chess reported errors on the selected game |
| `GAME_INDEX_OUT_OF_RANGE` | `game_index < 0` or `>= len(games)` |
| `GAME_TOO_LONG` | selected game has more than **600** plies |
| `UNSUPPORTED_VARIANT` | a `Variant` header is present and is not `Standard` / `standard` / `chess` |

Implementation note: parse the PGN with
`chess.pgn.read_game(io.StringIO(pgn))` in a loop until it returns `None`.
After reading the selected game, check `game.errors`; if non-empty, raise
`PGN_PARSE_ERROR` with `str(game.errors[0])`.

---

## 6. Data model (pydantic v2 models in `models.py`)

All models MUST serialise with these exact JSON keys.

### 6.1 `Gain`

```python
class Gain(BaseModel):
    kind: Literal["mate", "hanging", "favourable", "fork"]
    score: int          # see Section 7.4
    san: str            # SAN of the follow-up move that realises the gain,
                        #   e.g. "Qxf7#" (mate/hanging/favourable).
                        #   For kind == "fork": "" (empty string).
    square: str         # target square, e.g. "f7". For a fork: the square the
                        #   forking piece landed on, e.g. "d5".
    targets: list[str]  # for kind == "fork": the attacked squares, e.g.
                        #   ["f6", "e7"]. Empty list for all other kinds.
    text: str           # ready-to-display sentence, see Section 7.5
```

### 6.2 `Candidate`

```python
class Candidate(BaseModel):
    san: str            # "Qxf7#"
    uci: str            # "h5f7"
    from_square: str    # serialised as "from"  -> use Field(alias="from")
    to_square: str      # serialised as "to"
    piece: str          # uppercase piece letter of the mover: "P","N","B","R","Q","K"
    is_check: bool
    is_capture: bool
    is_mate: bool       # move is checkmate
    is_promotion: bool
    is_en_passant: bool
    captured: str | None  # uppercase letter of the captured piece, else None.
                          # En passant -> "P".
    played: bool        # True iff this move is the move actually played from
                        # this node in the game.
    score: int          # sort key, see Section 7.6
    gains: list[Gain]   # empty for checks/captures; 1..3 entries for threats
```

Configure the model with `populate_by_name=True` and serialise with
`by_alias=True` so the JSON keys are `from` and `to`.

### 6.3 `CctReport`

```python
class CctReport(BaseModel):
    checks: list[Candidate]
    captures: list[Candidate]
    threats: list[Candidate]
    counts: dict[str, int]      # {"checks": 2, "captures": 1, "threats": 11}
                                # counts are BEFORE truncation
    truncated: dict[str, bool]  # {"checks": False, "captures": False, "threats": True}
```

Lists are capped at **12** entries each (see Section 7.7). `counts` always
reports the untruncated totals.

### 6.4 `Node`

```python
class Node(BaseModel):
    index: int                    # 0 .. ply_count
    move_number: int              # full move number of the position (1-based)
    turn: Literal["w", "b"]       # side to move at this node
    fen: str
    san: str | None               # move played FROM this node; None at the last node
    uci: str | None
    last_move: dict | None        # {"from": "e2", "to": "e4"} — the move that
                                  # led INTO this node; None at node 0
    comment: str                  # PGN comment attached to the move played from
                                  # this node; "" if none
    in_check: bool
    is_checkmate: bool
    is_stalemate: bool
    cct: CctReport
```

---

## 7. The CCT engine (`cct.py`) — MUST implement exactly

This is the heart of the app. Implement it literally as written; the acceptance
tests in Section 11 depend on these precise rules.

### 7.0 Piece values

```python
VALUE = {PAWN: 1, KNIGHT: 3, BISHOP: 3, ROOK: 5, QUEEN: 9, KING: 100}
```

Helper `victim_value(board, move) -> int`: return `1` if
`board.is_en_passant(move)`, else `VALUE[board.piece_at(move.to_square).piece_type]`,
else `0`.

### 7.1 Checks

For every `move` in `board.legal_moves` where `board.gives_check(move)` is
`True`, emit a `Candidate`. Determine `is_mate` by `push` → `board.is_checkmate()`
→ `pop`.

**Sort key:** `(0 if is_mate else 1, 0 if is_capture else 1, san)`.
(Mates first, then checks that also capture, then alphabetical by SAN.)

### 7.2 Captures

For every `move` in `board.legal_moves` where `board.is_capture(move)` is
`True` (this already includes en passant), emit a `Candidate`.

**Sort key:** `(-victim_value, attacker_value, san)`.
(Biggest prize first; cheapest attacker first; then alphabetical.)

A move that is both a check and a capture appears in **both** lists.

### 7.3 The "gains" primitive

```python
def find_gains(board) -> dict[int, Gain]:
    """Material the side to move in `board` can win right now, keyed by target square."""
    them = not board.turn
    out = {}
    for move in board.generate_legal_captures():
        v = victim_value(board, move)
        a = VALUE[board.piece_at(move.from_square).piece_type]
        defended = bool(board.attackers(them, move.to_square))
        if not defended:
            kind = "hanging"        # win the whole piece
        elif v > a:
            kind = "favourable"     # win the difference even if recaptured
        else:
            continue                # even or losing capture: not a gain
        # keep only the most valuable gain per target square
        if move.to_square not in out or v > out[move.to_square].score:
            out[move.to_square] = Gain(kind=kind, score=v, san=board.san(move),
                                       square=square_name(move.to_square),
                                       targets=[], text=...)
    return out
```

```python
def find_mate_in_one(board) -> Move | None:
    """First legal move that is checkmate, else None. Only test checking moves —
    this is the whole performance trick."""
    for move in board.legal_moves:
        if board.gives_check(move):
            board.push(move)
            mate = board.is_checkmate()
            board.pop()
            if mate:
                return move
    return None
```

```python
def find_fork(board, square) -> list[tuple[int, str]] | None:
    """The piece standing on `square` (belongs to board.turn) attacks two or more
    enemy pieces worth >= 3. Returns [(value, square_name), ...] sorted by value
    descending, or None."""
    them = not board.turn
    targets = []
    for t in board.attacks(square):
        p = board.piece_at(t)
        if p and p.color == them and VALUE[p.piece_type] >= 3:
            targets.append((VALUE[p.piece_type], square_name(t)))
    targets.sort(reverse=True)
    return targets if len(targets) >= 2 else None
```

### 7.4 Threats

A threat is a **quiet move that creates a gain the mover did not already have.**

Algorithm, for a position `board` with mover `M`:

```
baseline_gains   = find_gains(board)                # what M can already win
baseline_squares = set(baseline_gains.keys())
baseline_mate    = find_mate_in_one(board) is not None

threats = []
for move in board.legal_moves:
    if board.gives_check(move) or board.is_capture(move):
        continue                                    # quiet moves only
    san = board.san(move)
    board.push(move)                                # now opponent to move
    board.push(Move.null())                         # flip back to M: "what if I
                                                    #   got to move again?"
    gains = []
    for square, gain in find_gains(board).items():
        if square not in baseline_squares:          # NEW gain only
            gains.append(gain)                      # score = victim value (1..9)

    mate = find_mate_in_one(board)
    if mate is not None and not baseline_mate:
        gains.append(Gain(kind="mate", score=1000, san=board.san(mate),
                          square=square_name(mate.to_square), targets=[]))

    fork = find_fork(board, move.to_square)
    if fork is not None:
        gains.append(Gain(kind="fork", score=fork[1][0],    # value of the SECOND
                          san="",                           #   target: what you
                          square=square_name(move.to_square),#  actually win
                          targets=[name for _, name in fork]))

    board.pop(); board.pop()

    if gains:
        gains.sort(key=lambda g: (-g.score, g.san))
        threats.append(Candidate(..., score=gains[0].score, gains=gains[:3]))
```

**Sort key for threats:** `(-score, san)` where `score` is the score of the
candidate's best gain.

**Why the null move is safe here:** the loop skips checking moves, so after
`push(move)` the opponent is never in check, and `push(Move.null())` returns a
legal position. Note that a null move clears the en-passant square; that is
accepted and irrelevant to the output.

### 7.5 `Gain.text` (display strings — MUST match exactly)

| kind | `text` |
|---|---|
| `mate` | `"threatens mate: {san}"` → `"threatens mate: Qxf7#"` |
| `hanging` | `"wins a hanging piece on {square}: {san}"` → `"wins a hanging piece on b7: Bxb7"` |
| `favourable` | `"wins material on {square}: {san}"` → `"wins material on d8: Bxd8"` |
| `fork` | `"double attack from {square} on {targets joined by ' and '}"` → `"double attack from d5 on f6 and e7"` |

### 7.6 `Candidate.score`

- In `checks`: `1000` if `is_mate` else `victim_value` if it captures else `0`.
- In `captures`: `victim_value`.
- In `threats`: the score of `gains[0]`.

`score` exists only so the frontend can render a strength bar; sorting is done
server-side and the frontend MUST preserve the received order.

### 7.7 Truncation

Each list is capped at **12** candidates after sorting. `counts` holds the
pre-truncation length, `truncated[list]` is `True` when the list was cut.
Exception: a candidate with `played == True` MUST always survive truncation —
if it falls outside the top 12, drop the last kept entry and append it.

### 7.8 Public API of `cct.py`

```python
def analyse(board: chess.Board, played: chess.Move | None = None) -> CctReport
```

`board` is not mutated (push/pop must be balanced — assert this in tests).
`played` marks the `played` flag on matching candidates.

### 7.9 Explicit non-goals

The engine does **not** do search, SEE, or evaluation. It will miss deep
threats (e.g. `Ng5` in the Italian threatening `Nxf7` forking queen and rook is
*not* reported, because `Nxf7` immediately loses material by the static rule).
That is accepted and MUST be disclosed in the UI (Section 9.7). Do not try to
"fix" it with a search.

---

## 8. Game analysis (`pgn.py`)

```python
def list_games(pgn_text: str) -> list[GameSummary]
def analyse_game(pgn_text: str, game_index: int = 0) -> AnalysedGame
```

Rules:

- **Mainline only.** Use `game.mainline()`. Ignore variations (RAVs) entirely.
- Ignore NAGs. Keep `node.comment` verbatim (stripped of surrounding whitespace)
  on the node the move is played *from*.
- Support non-standard start positions: use `game.board()`, which honours the
  `FEN` / `SetUp` headers.
- Reject a `Variant` header that is not standard chess (`UNSUPPORTED_VARIANT`).
- Reject games longer than 600 plies (`GAME_TOO_LONG`).
- Emit `ply_count + 1` `Node` objects. The final node has `san = None`,
  `uci = None`, and still carries a full `cct` report (useful: it shows what the
  losing side had available in the final position).
- `move_number` = `board.fullmove_number` at that node.
- Walk the game with a single `chess.Board`, calling `cct.analyse(board, played)`
  before each `board.push(move)`.

---

## 9. Frontend

Single page, three regions. No routing, no local storage, no service worker.

### 9.1 Layout

```
+--------------------------------------------------------------+
|  header: "CCT Viz"  ·  subtitle                              |
+---------------------------+----------------------------------+
|  LEFT COLUMN              |  RIGHT COLUMN                    |
|  - PGN input panel        |  - Position header               |
|    (textarea, Load game,  |    (move number, side to move,   |
|     file input, Load      |     status: check/mate/stalemate)|
|     example, game picker) |  - CHECKS list                   |
|  - Board (8x8)            |  - CAPTURES list                 |
|  - Nav bar                |  - THREATS list                  |
|    |< < [3/33] > >| Flip  |  - "played move" note            |
|  - FEN line (selectable)  |  - Move list (clickable)         |
+---------------------------+----------------------------------+
```

Use CSS Grid: two columns at viewport width >= 1000px, one stacked column below
that. The whole page must be usable at 1280x800 without horizontal scrolling.

### 9.2 PGN input panel

- A `<textarea id="pgn-input">`, 8 rows, monospace.
- **Load game** button → POST `/api/game`.
- `<input type="file" accept=".pgn,text/plain">` → read with `FileReader`,
  put the text in the textarea, then load automatically.
- **Load example** button → fetch `/static/example.pgn`, fill textarea, load.
  `example.pgn` contains Morphy's Opera Game:

  ```
  [Event "Paris"]
  [Site "Paris FRA"]
  [Date "1858.??.??"]
  [White "Paul Morphy"]
  [Black "Duke Karl / Count Isouard"]
  [Result "1-0"]

  1. e4 e5 2. Nf3 d6 3. d4 Bg4 4. dxe5 Bxf3 5. Qxf3 dxe5 6. Bc4 Nf6
  7. Qb3 Qe7 8. Nc3 c6 9. Bg5 b5 10. Nxb5 cxb5 11. Bxb5+ Nbd7 12. O-O-O Rd8
  13. Rxd7 Rxd7 14. Rd1 Qe6 15. Bxd7+ Nxd7 16. Qb8+ Nxb8 17. Rd8# 1-0
  ```

- If the response contains more than one game, show a `<select>` listing
  `"{index+1}. {white} – {black}, {event} {date} ({result})"`. Changing it
  re-POSTs the same PGN with the new `game_index`.
- On error, show the `error.message` in a red banner above the textarea. Leave
  any previously loaded game on screen.
- After a successful load, collapse the input panel to a single **Change PGN**
  button (click re-expands it).

### 9.3 Board rendering

- 64 `<div class="sq">` elements inside `<div id="board">`, `display: grid`,
  `grid-template-columns: repeat(8, 1fr)`, `aspect-ratio: 1 / 1`,
  `width: min(560px, 92vw)`.
- Rebuild from `node.fen` on every step (simplest correct approach — no
  animation, no diffing required).
- Light square `#EEEED2`, dark square `#769656`.
- Pieces are Unicode glyphs, `font-size: 78%` of square size, centred:

  | | K | Q | R | B | N | P |
  |---|---|---|---|---|---|---|
  | White | `♔` | `♕` | `♖` | `♗` | `♘` | `♙` |
  | Black | `♚` | `♛` | `♜` | `♝` | `♞` | `♟` |

  Glyph choice alone is not enough contrast on green squares, so also set
  `color: #ffffff` with `text-shadow: 0 0 2px #000, 0 1px 2px #000` for white
  pieces and `color: #111111` for black pieces. Both colours must be legible on
  both square colours.
- File letters `a–h` along the bottom edge and rank numbers `1–8` along the left
  edge, as small labels in the corner of each edge square.
- **Flip**: a toggle that reverses the rendering order. Default orientation is
  White at the bottom.
- Every square carries `data-square="e4"`.

### 9.4 Square highlighting

Highlight classes, applied by adding a CSS class to the square div:

| class | colour | when |
|---|---|---|
| `hl-last` | `rgba(255, 214, 0, 0.45)` | the `from` and `to` squares of `node.last_move` |
| `hl-cand-from` | `rgba(64, 130, 255, 0.55)` | `from` square of the hovered/focused candidate |
| `hl-cand-to` | `rgba(64, 130, 255, 0.75)` | `to` square of the hovered/focused candidate |
| `hl-gain` | `rgba(255, 92, 92, 0.60)` | for a hovered threat: `gains[0].square` and every square in `gains[0].targets` |

Candidate highlights are applied on `mouseenter` / `focus` of a candidate row
and removed on `mouseleave` / `blur`. `hl-last` is always on.

### 9.5 Navigation

Buttons: `|<` (start), `<` (previous), `>` (next), `>|` (end), and a counter
`ply 3 / 33`. Plus a **Flip board** button.

Keyboard (bound on `document`, but **ignored when the event target is a
`<textarea>`, `<input>`, or `<select>`**):

| key | action |
|---|---|
| `ArrowRight`, `ArrowDown`, `Space` | next ply |
| `ArrowLeft`, `ArrowUp` | previous ply |
| `Home` | node 0 |
| `End` | last node |
| `f` | flip board |

Clamp at both ends; do not wrap. Buttons are `disabled` at the ends.

### 9.6 CCT panel

Three sections, in this order: **Checks**, **Captures**, **Threats**. Each has a
header showing the name and `counts[...]`, e.g. `Threats (11)`. Each is a list of
candidate rows:

```
[ Qxf7# ]  checkmate                              <- check row
[ Bxb7  ]  takes pawn on b7                       <- capture row
[ Bc4   ]  threatens mate: Qxf7#         [played] <- threat row
```

Row requirements:

- The SAN is rendered in a monospace chip.
- A capture row's detail text is `"takes {piece word} on {to}"`, where piece word
  comes from `captured`: `P`→`pawn`, `N`→`knight`, `B`→`bishop`, `R`→`rook`,
  `Q`→`queen`. Append `" (en passant)"` when `is_en_passant`.
- A check row's detail text is `"checkmate"` if `is_mate`, else `"check"`.
- A threat row's detail text is `gains[0].text`. If the candidate has more than
  one gain, append `" (+{n} more)"`.
- A row with `played: true` gets a `played` badge and a highlighted background.
- Rows are focusable (`tabindex="0"`) so keyboard users get the highlighting.
- If `truncated[list]` is true, append a muted line: `showing top 12 of {count}`.
- An empty list shows a muted `none`.
- Below the three sections, a note about the move actually played:
  - if the played move appears in at least one list:
    `Played: {san} — appears in Checks / Captures / Threats.` (name only the
    lists it is actually in)
  - if it does not: `Played: {san} — not a check, capture, or threat.`
  - at the final node: `End of game. Result: {result}.`

### 9.7 Required disclaimer

Under the CCT panel, in muted small text, verbatim:

> Candidate enumeration only — no engine search. Threats are found by a
> one-move static scan, so deep tactics (forks two moves away, pins, skewers,
> zwischenzugs) will be missed.

### 9.8 Move list

A two-column-per-row list: move number, White SAN, Black SAN. The SAN belonging
to the current node's *incoming* move is highlighted. Clicking any SAN jumps to
the node *after* that move. The list auto-scrolls to keep the current move
visible. A move with a non-empty `comment` shows a `💬` marker with the comment
as its `title` attribute.

### 9.9 Client state

```js
const state = {
  pgnText: "",      // the raw PGN, kept so we can re-POST on game change
  games: [],        // summaries
  selected: 0,
  game: null,       // AnalysedGame from the server
  ply: 0,           // current node index
  flipped: false,
};
```

All stepping is **client-side only** — the server sends the fully analysed game
in one response, so `→` must never trigger a network request.

---

## 10. Performance

- Reference measurement (taken with python-chess 1.11 on a normal laptop):
  analysing an 87-ply master game with this exact algorithm takes **~1.1 s**.
- Budget: a 100-ply game MUST analyse in **under 3 seconds**.
- The `find_mate_in_one` optimisation (only push moves where `gives_check` is
  true) and using `generate_legal_captures()` rather than filtering all legal
  moves are what make this budget achievable. Do not replace them with naive
  loops.
- Show an "Analysing…" state in the UI while the POST is in flight.

---

## 11. Acceptance tests (MUST pass — values below are verified output)

Put these in `tests/`. Compare SAN lists exactly, including order.

### 11.1 Starting position — nothing forcing exists

FEN: `rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1`

```
checks   == []
captures == []
threats  == []
```

### 11.2 After `1.e4` — three pawn-grabbing threats, nothing else

FEN: `rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1`

```
checks   == []
captures == []
threat SANs == ["Nf6", "d5", "f5"]
```

Each threat has exactly one gain: `kind == "hanging"`, `score == 1`, targeting
`e4` (`Nxe4`, `dxe4`, `fxe4` respectively).

### 11.3 Scholar's-mate position — mate sorts to the top of Checks

Position after `1.e4 e5 2.Bc4 Nc6 3.Qh5 Nf6`, White to move.
FEN: `r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4`

```
checks   == ["Qxf7#", "Bxf7+", "Qxe5+"]
captures == ["Bxf7+", "Qxe5+", "Qxf7#", "Qxh7"]
threats  == []
```

(Checks: mate first, then the capturing checks alphabetically. Captures: every
victim is a pawn worth 1, so the cheapest attacker comes first — bishop before
queen — then alphabetical.)

### 11.4 Opera Game before `6.Bc4` — the real mate threat is found and ranked first

Position after `1.e4 e5 2.Nf3 d6 3.d4 Bg4 4.dxe5 Bxf3 5.Qxf3 dxe5`, White to move.
FEN: `rn1qkbnr/ppp2ppp/8/4p3/4P3/5Q2/PPP2PPP/RNB1KB1R w KQkq - 0 6`

```
checks   == ["Qxf7+", "Bb5+"]
captures == ["Qxf7+"]
counts["threats"] == 11
threats[0].san == "Bc4"
threats[0].gains[0].kind == "mate"
threats[0].gains[0].san  == "Qxf7#"
threats[0].gains[0].text == "threatens mate: Qxf7#"
threats[1].san == "Bg5"
threats[1].gains[0].kind == "favourable"      # Bxd8 wins the queen
threats[1].gains[0].score == 9
```

The remaining nine threats all have `score == 1` (hanging-pawn gains) and are
sorted alphabetically by SAN:
`Ba6, Bf4, Qb3, Qc3, Qf4, Qf5, Qf6, Qg3, Qh5`.

### 11.5 Board purity

`cct.analyse(board)` MUST leave `board.fen()` and `len(board.move_stack)`
unchanged. Assert this.

### 11.6 Full-game analysis

Analysing the Opera Game (Section 9.2) yields:

```
ply_count  == 33
len(plies) == 34
plies[0].san == "e4"   and plies[0].turn == "w"  and plies[0].last_move is None
plies[32].san == "Rd8#"
plies[33].san is None  and plies[33].is_checkmate is True
```

At `plies[32]`, the candidate with `san == "Rd8#"` in `checks` has
`played is True` and `is_mate is True`.

### 11.7 API tests (`TestClient`)

- `POST /api/game` with the example PGN → `200`, `len(body["games"]) == 1`,
  `len(body["game"]["plies"]) == 34`.
- `POST /api/game` with `{"pgn": "   "}` → `400`, `error.code == "PGN_EMPTY"`.
- `POST /api/game` with the example PGN and `"game_index": 5` → `400`,
  `error.code == "GAME_INDEX_OUT_OF_RANGE"`.
- `POST /api/game` with a PGN containing an illegal move (e.g. `1. e4 e5 2. Ke3`)
  → `400`, `error.code == "PGN_PARSE_ERROR"`.
- A PGN containing two games concatenated → `len(body["games"]) == 2`, and
  `game_index=1` returns the second game.
- `GET /api/health` → `200`, `{"status": "ok", ...}`.
- `GET /` → `200`, `text/html`, body contains `id="board"`.

---

## 12. Out of scope (do NOT build)

- Engine evaluation, best-move suggestions, blunder detection, accuracy scores.
- Variations / RAV navigation, editing moves, playing moves on the board.
- Chess960 or any non-standard variant.
- Opening books, tablebases, network lookups of any kind.
- User accounts, persistence, databases, saving games.
- Arrows or drag-and-drop on the board (square highlights only).
- Dark mode toggle. Pick one light theme and ship it.
- Mobile-optimised layout beyond the single-column stack at < 1000px.

---

## 13. Definition of done

1. `pip install -e ".[dev]"` succeeds on a clean Python 3.11+ environment.
2. `pytest -q` passes with every test in Section 11 present and green.
3. `python -m cct_viz` serves the app; loading the example PGN and pressing `→`
   through the whole game works with no console errors and no network requests
   after the initial load.
4. At the position before `6.Bc4` in the example game, the Threats list shows
   `Bc4 — threatens mate: Qxf7#` as the first entry, badged **played**.
5. `README.md` documents install, run, test, the CCT definitions from Section 7,
   and the known limitations from Section 7.9.
