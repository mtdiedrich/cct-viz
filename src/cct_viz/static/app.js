"use strict";

/* CCT Viz frontend (spec section 9).
 *
 * The server sends the entire analysed game in one POST response; every
 * subsequent step through the game is client-side only. No network request is
 * made when navigating.
 */

const state = {
  pgnText: "",
  games: [],
  selected: 0,
  game: null,
  ply: 0,
  flipped: false,
};

// Use the solid (filled) glyphs for both colours; the white pieces are then
// recoloured white with a dark outline in CSS so they read as filled shapes
// rather than the thin outline glyphs (U+2654..U+2659).
const PIECE_GLYPH = {
  P: "♟", N: "♞", B: "♝", R: "♜", Q: "♛", K: "♚",
  p: "♟", n: "♞", b: "♝", r: "♜", q: "♛", k: "♚",
};
const PIECE_WORD = { P: "pawn", N: "knight", B: "bishop", R: "rook", Q: "queen" };

const $ = (id) => document.getElementById(id);

/* ------------------------------------------------------------------ */
/* Loading a game                                                      */
/* ------------------------------------------------------------------ */

async function loadGame(gameIndex) {
  const pgn = $("pgn-input").value;
  showAnalysing(true);
  hideError();
  try {
    const resp = await fetch("/api/game", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pgn, game_index: gameIndex }),
    });
    const body = await resp.json();
    if (!resp.ok) {
      const msg = body && body.error ? body.error.message : "Could not load game.";
      showError(msg);
      return;
    }
    state.pgnText = pgn;
    state.games = body.games;
    state.selected = body.selected_index;
    state.game = body.game;
    state.ply = 0;
    renderGamePicker();
    collapsePgnPanel();
    renderAll();
  } catch (err) {
    showError("Network error: " + err.message);
  } finally {
    showAnalysing(false);
  }
}

function renderGamePicker() {
  const wrap = $("game-picker-wrap");
  const picker = $("game-picker");
  if (state.games.length <= 1) {
    wrap.hidden = true;
    picker.innerHTML = "";
    return;
  }
  wrap.hidden = false;
  picker.innerHTML = "";
  state.games.forEach((g) => {
    const opt = document.createElement("option");
    opt.value = String(g.index);
    opt.textContent = `${g.index + 1}. ${g.white} – ${g.black}, ${g.event} ${g.date} (${g.result})`;
    if (g.index === state.selected) opt.selected = true;
    picker.appendChild(opt);
  });
}

/* ------------------------------------------------------------------ */
/* PGN panel show / hide                                               */
/* ------------------------------------------------------------------ */

function collapsePgnPanel() {
  $("pgn-form").hidden = true;
  $("change-pgn").hidden = false;
}
function expandPgnPanel() {
  $("pgn-form").hidden = false;
  $("change-pgn").hidden = true;
}
function showError(message) {
  const banner = $("pgn-error");
  banner.textContent = message;
  banner.hidden = false;
}
function hideError() {
  $("pgn-error").hidden = true;
}
function showAnalysing(on) {
  $("analysing").hidden = !on;
}

/* ------------------------------------------------------------------ */
/* Navigation                                                          */
/* ------------------------------------------------------------------ */

function lastPly() {
  return state.game ? state.game.plies.length - 1 : 0;
}
function goto(ply) {
  if (!state.game) return;
  state.ply = Math.max(0, Math.min(lastPly(), ply));
  renderAll();
}
function flip() {
  state.flipped = !state.flipped;
  renderBoard();
}

document.addEventListener("keydown", (e) => {
  const tag = (e.target.tagName || "").toLowerCase();
  if (tag === "textarea" || tag === "input" || tag === "select") return;
  switch (e.key) {
    case "ArrowRight": case "ArrowDown": case " ":
      e.preventDefault(); goto(state.ply + 1); break;
    case "ArrowLeft": case "ArrowUp":
      e.preventDefault(); goto(state.ply - 1); break;
    case "Home":
      e.preventDefault(); goto(0); break;
    case "End":
      e.preventDefault(); goto(lastPly()); break;
    case "f": case "F":
      flip(); break;
  }
});

/* ------------------------------------------------------------------ */
/* Rendering                                                           */
/* ------------------------------------------------------------------ */

function currentNode() {
  return state.game.plies[state.ply];
}

function renderAll() {
  if (!state.game) return;
  renderBoard();
  renderNav();
  renderPositionHeader();
  renderCct();
  renderMoveList();
  $("fen-line").textContent = currentNode().fen;
}

function parseFenBoard(fen) {
  // returns map: squareName -> pieceChar
  const placement = fen.split(" ")[0];
  const rows = placement.split("/");
  const pieces = {};
  for (let r = 0; r < 8; r++) {
    const rank = 8 - r;
    let file = 0;
    for (const ch of rows[r]) {
      if (/\d/.test(ch)) {
        file += parseInt(ch, 10);
      } else {
        const name = "abcdefgh"[file] + rank;
        pieces[name] = ch;
        file += 1;
      }
    }
  }
  return pieces;
}

function renderBoard() {
  const board = $("board");
  board.innerHTML = "";
  const node = currentNode();
  const pieces = parseFenBoard(node.fen);

  const ranks = state.flipped ? [1, 2, 3, 4, 5, 6, 7, 8] : [8, 7, 6, 5, 4, 3, 2, 1];
  const files = state.flipped ? ["h", "g", "f", "e", "d", "c", "b", "a"]
                              : ["a", "b", "c", "d", "e", "f", "g", "h"];

  ranks.forEach((rank, rIdx) => {
    files.forEach((file, fIdx) => {
      const name = file + rank;
      const sq = document.createElement("div");
      // a1 is a dark square: (file index + rank) even -> light, odd -> dark
      sq.className = "sq " + (((file.charCodeAt(0) - 97) + rank) % 2 === 0 ? "light" : "dark");
      sq.dataset.square = name;

      const ch = pieces[name];
      if (ch) {
        const span = document.createElement("span");
        span.className = "piece " + (ch === ch.toUpperCase() ? "white" : "black");
        span.textContent = PIECE_GLYPH[ch];
        sq.appendChild(span);
      }
      if (rIdx === 7) sq.appendChild(coord("file", file));
      if (fIdx === 0) sq.appendChild(coord("rank", String(rank)));

      board.appendChild(sq);
    });
  });

  if (node.last_move) {
    markSquare(node.last_move.from, "hl-last");
    markSquare(node.last_move.to, "hl-last");
  }
}

function coord(kind, text) {
  const el = document.createElement("span");
  el.className = "coord " + kind;
  el.textContent = text;
  return el;
}
function markSquare(name, cls) {
  const el = document.querySelector(`#board .sq[data-square="${name}"]`);
  if (el) el.classList.add(cls);
}
function clearMarks(cls) {
  document.querySelectorAll("#board .sq." + cls).forEach((el) => el.classList.remove(cls));
}

function renderNav() {
  const n = lastPly();
  $("nav-counter").textContent = `ply ${state.ply} / ${n}`;
  $("nav-start").disabled = state.ply === 0;
  $("nav-prev").disabled = state.ply === 0;
  $("nav-next").disabled = state.ply === n;
  $("nav-end").disabled = state.ply === n;
}

function renderPositionHeader() {
  const node = currentNode();
  $("position-move").textContent = `Move ${node.move_number}`;
  $("position-turn").textContent = node.turn === "w" ? "White to move" : "Black to move";
  let status = "";
  if (node.is_checkmate) status = "checkmate";
  else if (node.is_stalemate) status = "stalemate";
  else if (node.in_check) status = "check";
  $("position-status").textContent = status;
}

/* ---------- CCT panel ---------- */

function captureWord(c) {
  let word = "takes " + (PIECE_WORD[c.captured] || "piece") + " on " + c.to;
  if (c.is_en_passant) word += " (en passant)";
  return word;
}
function checkWord(c) {
  return c.is_mate ? "checkmate" : "check";
}
function threatWord(c) {
  let text = c.gains.length ? c.gains[0].text : "";
  if (c.gains.length > 1) text += ` (+${c.gains.length - 1} more)`;
  return text;
}

function strengthPx(c) {
  // score is either a material value (0..9), 1000 for a mate, or the
  // best-gain score of a threat. Map it onto a 4..48px bar.
  const isMate = c.score >= 1000;
  const frac = isMate ? 1 : Math.min(1, c.score / 9);
  return Math.round(4 + frac * 44);
}

function candidateRow(c, kind) {
  const li = document.createElement("li");
  li.tabIndex = 0;
  if (c.played) li.classList.add("played");

  const chip = document.createElement("span");
  chip.className = "san-chip";
  chip.textContent = c.san;
  li.appendChild(chip);

  const detail = document.createElement("span");
  detail.className = "cand-detail";
  detail.textContent =
    kind === "checks" ? checkWord(c) :
    kind === "captures" ? captureWord(c) :
    threatWord(c);
  li.appendChild(detail);

  const bar = document.createElement("span");
  bar.className = "cand-bar";
  bar.style.width = strengthPx(c) + "px";
  li.appendChild(bar);

  if (c.played) {
    const badge = document.createElement("span");
    badge.className = "played-badge";
    badge.textContent = "played";
    li.appendChild(badge);
  }

  const enter = () => highlightCandidate(c, kind);
  const leave = () => {
    clearMarks("hl-cand-from");
    clearMarks("hl-cand-to");
    clearMarks("hl-gain");
  };
  li.addEventListener("mouseenter", enter);
  li.addEventListener("mouseleave", leave);
  li.addEventListener("focus", enter);
  li.addEventListener("blur", leave);
  return li;
}

function highlightCandidate(c, kind) {
  clearMarks("hl-cand-from");
  clearMarks("hl-cand-to");
  clearMarks("hl-gain");
  markSquare(c.from, "hl-cand-from");
  markSquare(c.to, "hl-cand-to");
  if (kind === "threats" && c.gains.length) {
    const g = c.gains[0];
    if (g.square) markSquare(g.square, "hl-gain");
    (g.targets || []).forEach((t) => markSquare(t, "hl-gain"));
  }
}

function fillList(listId, countId, candidates, count, truncated, kind) {
  const ul = $(listId);
  ul.innerHTML = "";
  $(countId).textContent = `(${count})`;
  if (!candidates.length) {
    const li = document.createElement("li");
    li.className = "list-note";
    li.textContent = "none";
    ul.appendChild(li);
    return;
  }
  candidates.forEach((c) => ul.appendChild(candidateRow(c, kind)));
  if (truncated) {
    const li = document.createElement("li");
    li.className = "list-note";
    li.textContent = `showing top 12 of ${count}`;
    ul.appendChild(li);
  }
}

function renderCct() {
  const node = currentNode();
  const r = node.cct;
  fillList("list-checks", "count-checks", r.checks, r.counts.checks, r.truncated.checks, "checks");
  fillList("list-captures", "count-captures", r.captures, r.counts.captures, r.truncated.captures, "captures");
  fillList("list-threats", "count-threats", r.threats, r.counts.threats, r.truncated.threats, "threats");
  renderPlayedNote(node);
}

function renderPlayedNote(node) {
  const el = $("played-note");
  if (node.san === null) {
    el.textContent = `End of game. Result: ${state.game.result}.`;
    return;
  }
  const inLists = [];
  const has = (list) => list.some((c) => c.san === node.san);
  if (has(node.cct.checks)) inLists.push("Checks");
  if (has(node.cct.captures)) inLists.push("Captures");
  if (has(node.cct.threats)) inLists.push("Threats");
  if (inLists.length) {
    el.textContent = `Played: ${node.san} — appears in ${inLists.join(" / ")}.`;
  } else {
    el.textContent = `Played: ${node.san} — not a check, capture, or threat.`;
  }
}

/* ---------- Move list ---------- */

function renderMoveList() {
  const ol = $("movelist");
  ol.innerHTML = "";
  const plies = state.game.plies;
  const moveCount = plies.length - 1; // last node has no move

  let current = null;
  for (let i = 0; i < moveCount; i += 2) {
    const li = document.createElement("li");
    const num = document.createElement("span");
    num.className = "num";
    num.textContent = plies[i].move_number + ".";
    li.appendChild(num);

    li.appendChild(sanCell(i));
    if (i + 1 < moveCount) li.appendChild(sanCell(i + 1));
    else li.appendChild(document.createElement("span"));

    ol.appendChild(li);
  }

  // highlight the incoming move of the current node
  if (state.ply > 0) {
    const cell = ol.querySelector(`.san[data-ply="${state.ply - 1}"]`);
    if (cell) {
      cell.classList.add("current");
      current = cell;
    }
  }
  if (current) current.scrollIntoView({ block: "nearest" });
}

function sanCell(moveIdx) {
  const node = state.game.plies[moveIdx];
  const span = document.createElement("span");
  span.className = "san";
  span.dataset.ply = String(moveIdx);
  span.textContent = node.san;
  if (node.comment) {
    const mark = document.createElement("span");
    mark.className = "comment-mark";
    mark.textContent = " 💬";
    mark.title = node.comment;
    span.appendChild(mark);
  }
  span.addEventListener("click", () => goto(moveIdx + 1));
  return span;
}

/* ------------------------------------------------------------------ */
/* Wiring                                                              */
/* ------------------------------------------------------------------ */

function init() {
  $("load-game").addEventListener("click", () => loadGame(0));
  $("load-example").addEventListener("click", async () => {
    const resp = await fetch("/static/example.pgn");
    $("pgn-input").value = await resp.text();
    loadGame(0);
  });
  $("pgn-file").addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      $("pgn-input").value = String(reader.result);
      loadGame(0);
    };
    reader.readAsText(file);
  });
  $("game-picker").addEventListener("change", (e) => {
    loadGame(parseInt(e.target.value, 10));
  });
  $("change-pgn").addEventListener("click", expandPgnPanel);

  $("nav-start").addEventListener("click", () => goto(0));
  $("nav-prev").addEventListener("click", () => goto(state.ply - 1));
  $("nav-next").addEventListener("click", () => goto(state.ply + 1));
  $("nav-end").addEventListener("click", () => goto(lastPly()));
  $("nav-flip").addEventListener("click", flip);
}

init();
