# CCT Viz

A local web app for stepping through a PGN chess game one half-move at a time
and reading the **CCT report** — Checks, Captures, Threats — for the side to
move at every position.

CCT is a human tactical-scanning heuristic: *list the forcing moves before you
decide*. This app is a **candidate-move enumerator**, not a chess engine. It
does no search and gives no evaluation.

## Install

Requires Python 3.11+.

```bash
pip install -e ".[dev]"
```

If you cannot install the package (e.g. a read-only environment), the test
suite also runs directly from the source tree because `pyproject.toml` sets
`pythonpath = ["src"]`.

## Run

```bash
python -m cct_viz
```

Then open <http://127.0.0.1:8000/>. Options:

```bash
python -m cct_viz --host 0.0.0.0 --port 9000
```

Paste a PGN and click **Load game**, or click **Load example** for Morphy's
Opera Game. Step with the on-screen buttons or the keyboard:

| key | action |
|---|---|
| `→` `↓` `Space` | next ply |
| `←` `↑` | previous ply |
| `Home` / `End` | first / last node |
| `f` | flip board |

All stepping is client-side; the whole analysed game arrives in one response
and navigation never hits the network.

## Test

```bash
pytest -q
```

The suite in `tests/` is the acceptance suite from
`docs/spec/0-cct-viz-spec.md` section 11 (exact SAN lists and gain values for the
starting position, `1.e4`, the Scholar's-mate position, and the Opera Game),
plus board-purity, full-game, and API tests.

## The CCT engine (`src/cct_viz/cct.py`)

Piece values: `P=1, N=3, B=3, R=5, Q=9, K=100`.

* **Checks** — every legal move for which `board.gives_check` is true.
  Sorted: mates first, then checks that also capture, then alphabetical by SAN.
* **Captures** — every legal move for which `board.is_capture` is true
  (en passant included). Sorted: biggest victim first, then cheapest attacker,
  then alphabetical. A move that is both a check and a capture appears in
  **both** lists.
* **Threats** — every legal *quiet* move (not a check, not a capture) that
  creates a **new gain** the mover did not already have. A gain is one of:
  * `hanging` — a capture of an undefended enemy piece;
  * `favourable` — a capture where the victim is worth more than the attacker,
    so material is won even after the recapture;
  * `mate` — a mate in one becomes available (and was not available before);
  * `fork` — the moved piece now attacks two or more enemy pieces worth ≥ 3.

  The scan looks one move ahead: after the quiet move it pushes a null move
  ("what if I got to move again?") and re-runs the static gain finder, keeping
  only gains on squares that were not already winnable. Threats are sorted by
  the score of their best gain (descending), then by SAN.

Each candidate carries a `score` (used only for the strength bar in the UI),
the `from`/`to` squares, `played` (true for the move actually made in the game),
and, for threats, up to three `gains` with ready-to-display `text`.

Lists are capped at 12 entries after sorting; `counts` reports the
pre-truncation totals. A candidate marked `played` always survives truncation.

`analyse()` never mutates the board it is given (asserted in the tests).

## Known limitations (by design)

The engine does **no search, no static-exchange evaluation, and no position
evaluation.** It will miss:

* threats that only work two or more moves deep (e.g. `Ng5` in the Italian
  threatening `Nxf7` to fork queen and rook — `Nxf7` loses material by the
  static rule, so `Ng5` is not reported);
* pins, skewers, discovered attacks, and zwischenzugs;
* whether a "threat" it reports is actually good once the opponent replies.

This is a scanning aid, not an analysis engine. The same disclaimer appears in
the UI under the CCT panel.

## Layout

```
pyproject.toml
src/cct_viz/
  __main__.py     python -m cct_viz
  models.py       pydantic models
  cct.py          the CCT engine
  pgn.py          PGN parsing + game analysis
  server.py       FastAPI app (API + static frontend)
  static/         index.html, styles.css, app.js, example.pgn
tests/            acceptance tests
docs/spec/        build specifications, numbered in build order
  0-cct-viz-spec.md    PGN step-through (this app)
  1-play-mode-spec.md  Play Mode: play both sides, CCT for both colours
```

## API

| method + path | purpose |
|---|---|
| `GET /` | the single-page frontend |
| `GET /static/*` | static assets |
| `GET /api/health` | `{"status": "ok", "version": "0.1.0"}` |
| `POST /api/game` | `{"pgn": "...", "game_index": 0}` → the fully analysed game |

Errors are always HTTP 400 with `{"error": {"code": "...", "message": "..."}}`.
Codes: `PGN_EMPTY`, `PGN_NO_GAMES`, `PGN_PARSE_ERROR`,
`GAME_INDEX_OUT_OF_RANGE`, `GAME_TOO_LONG`, `UNSUPPORTED_VARIANT`.

## Notes / ambiguities resolved

* The final node of a game carries a full (usually empty) CCT report, per spec
  section 8.
* `GameSummary` string headers fall back to `"?"` (or `"????.??.??"` for a
  missing date) when a header is absent.
* A gain's follow-up SAN is rendered in the hypothetical post-null position, so
  it may carry a `+` (e.g. `Qxe5+`) even though the threat move itself is quiet.
* Board glyphs deviate from the spec 9.3 table: both colours use the *filled*
  chess glyphs (U+265A..U+265F) and the white pieces are recoloured white with a
  dark outline in CSS. The thin outline glyphs (U+2654..U+2659) read poorly at
  board size, especially on the green squares. Colours and contrast still meet
  the spec's intent (white legible on both square colours, black likewise).
