"use strict";

/* CCT Viz — Play Mode frontend (play-mode spec sections 8 & 9).
 *
 * The server is stateless. The client owns the line (a start FEN plus a list
 * of UCI moves) and the analysed nodes. Playing a move fetches exactly one new
 * node; navigation is pure array indexing and issues no request.
 *
 * The helpers between the two RULES markers are copied verbatim from app.js
 * (play-mode spec 8.1) — do not "improve" them or the acceptance strings drift.
 */

/* ===== RULES: copied verbatim from app.js ========================== */

const PIECE_GLYPH = {
  P: "♟", N: "♞", B: "♝", R: "♜", Q: "♛", K: "♚",
  p: "♟", n: "♞", b: "♝", r: "♜", q: "♛", k: "♚",
};
const PIECE_WORD = { P: "pawn", N: "knight", B: "bishop", R: "rook", Q: "queen" };

function parseFenBoard(fen) {
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
  const isMate = c.score >= 1000;
  const frac = isMate ? 1 : Math.min(1, c.score / 9);
  return Math.round(4 + frac * 44);
}

/* ===== RULES: end of verbatim copies ============================== */

const $ = (id) => document.getElementById(id);
const STORAGE_KEY = "cctviz.play.v1";
const START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";

const state = {
  startFen: null,   // null = standard start
  moves: [],        // UCI strings
  nodes: [],        // PlyNode[]; nodes[i].index === i
  cursor: 0,        // which node is displayed
  flipped: false,
  selected: null,   // selected origin square name, or null
  pinned: null,     // {uci, color} of a pinned CCT highlight, or null
};

/* ------------------------------------------------------------------ */
/* Server                                                             */
/* ------------------------------------------------------------------ */

async function apiPlay(analyseFrom) {
  const resp = await fetch("/api/play", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      start_fen: state.startFen,
      moves: state.moves,
      analyse_from: analyseFrom,
    }),
  });
  const body = await resp.json();
  if (!resp.ok) {
    const msg = body && body.error ? body.error.message : "Request failed.";
    const err = new Error(msg);
    err.code = body && body.error ? body.error.code : null;
    throw err;
  }
  return body;
}

/* Full (re)fetch: replace every node. */
async function refetchAll() {
  hideError();
  const body = await apiPlay(0);
  state.startFen = body.start_fen === START_FEN ? state.startFen : body.start_fen;
  state.moves = body.moves.slice();
  state.nodes = body.plies.slice();
  if (state.cursor > state.nodes.length - 1) state.cursor = state.nodes.length - 1;
  state.selected = null;
  state.pinned = null;
  persist();
  renderAll();
}

/* ------------------------------------------------------------------ */
/* Making a move                                                      */
/* ------------------------------------------------------------------ */

function atTip() {
  return state.cursor === state.nodes.length - 1;
}
function currentNode() {
  return state.nodes[state.cursor];
}

async function playMove(uci) {
  const node = currentNode();
  if (node.is_game_over) {
    setStatus(gameOverText(node));
    return;
  }

  let truncatedAt = null;
  if (!atTip()) {
    truncatedAt = state.cursor;
    state.moves = state.moves.slice(0, state.cursor);
    state.nodes = state.nodes.slice(0, state.cursor + 1);
  }

  state.moves.push(uci);
  state.selected = null;
  state.pinned = null;

  try {
    const body = await apiPlay(state.moves.length);
    state.nodes.push(body.plies[0]);
    state.cursor = state.nodes.length - 1;
    persist();
    renderAll();
    if (truncatedAt !== null) {
      setStatus(`Line truncated at ply ${truncatedAt}.`);
    }
  } catch (err) {
    state.moves.pop();               // roll back (spec 9.2 step 4)
    if (truncatedAt !== null) {
      // A truncating move failed: restore what we dropped by refetching.
      await refetchAll().catch(() => {});
    }
    showError(err.message);
    renderAll();
  }
}

/* ------------------------------------------------------------------ */
/* Board interaction                                                  */
/* ------------------------------------------------------------------ */

function legalFrom(sq) {
  return currentNode().legal_moves.filter((m) => m.from === sq);
}

function selectSquare(sq) {
  const node = currentNode();
  const pieces = parseFenBoard(node.fen);
  const ch = pieces[sq];
  const whiteToMove = node.turn === "w";
  const isOwnPiece = ch && (ch === ch.toUpperCase()) === whiteToMove;

  if (state.selected === sq) {
    state.selected = null;
    renderBoard();
    return;
  }
  if (state.selected && !isOwnPiece) {
    // second click: try to move selected -> sq
    tryMove(state.selected, sq);
    return;
  }
  if (isOwnPiece && !node.is_game_over) {
    // Selecting is allowed even when the cursor is behind the tip; playing the
    // move then truncates the line (spec 9.4).
    state.selected = sq;
    renderBoard();
  } else {
    state.selected = null;
    renderBoard();
  }
}

function tryMove(from, to) {
  const matches = currentNode().legal_moves.filter((m) => m.from === from && m.to === to);
  if (matches.length === 0) {
    state.selected = null;
    renderBoard();
    return;
  }
  if (matches.length === 1) {
    playMove(matches[0].uci);
    return;
  }
  // promotion: several moves share from/to
  openPromoChooser((piece) => {
    if (!piece) { state.selected = null; renderBoard(); return; }
    const chosen = matches.find((m) => m.promotion === piece);
    if (chosen) playMove(chosen.uci);
  });
}

function openPromoChooser(cb) {
  const box = $("promo-chooser");
  box.hidden = false;
  const handler = (e) => {
    const btn = e.target.closest("button[data-p]");
    if (!btn) return;
    box.hidden = true;
    box.removeEventListener("click", handler);
    cb(btn.dataset.p);
  };
  box.addEventListener("click", handler);
}

/* ------------------------------------------------------------------ */
/* Navigation                                                         */
/* ------------------------------------------------------------------ */

function lastCursor() {
  return state.nodes.length - 1;
}
function goto(cursor) {
  state.cursor = Math.max(0, Math.min(lastCursor(), cursor));
  state.selected = null;
  state.pinned = null;
  persist();
  renderAll();
}
function flip() {
  state.flipped = !state.flipped;
  persist();
  renderBoard();
}
function takeback() {
  if (state.moves.length === 0) return;
  state.moves.pop();
  state.nodes.pop();
  state.cursor = lastCursor();
  state.selected = null;
  state.pinned = null;
  persist();
  renderAll();
}

document.addEventListener("keydown", (e) => {
  const tag = (e.target.tagName || "").toLowerCase();
  if (tag === "textarea" || tag === "input" || tag === "select") return;
  switch (e.key) {
    case "ArrowRight": e.preventDefault(); goto(state.cursor + 1); break;
    case "ArrowLeft": e.preventDefault(); goto(state.cursor - 1); break;
    case "Home": e.preventDefault(); goto(0); break;
    case "End": e.preventDefault(); goto(lastCursor()); break;
    case "f": case "F": flip(); break;
    case "u": case "U": takeback(); break;
  }
});

/* ------------------------------------------------------------------ */
/* Rendering                                                          */
/* ------------------------------------------------------------------ */

function renderAll() {
  renderBoard();
  renderNav();
  renderPanels();
  renderMoveList();
  renderStatus();
  $("fen-line").textContent = currentNode().fen;
}

const PIECE_NAME = { p: "pawn", n: "knight", b: "bishop", r: "rook", q: "queen", k: "king" };

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
      sq.className = "sq " + (((file.charCodeAt(0) - 97) + rank) % 2 === 0 ? "light" : "dark");
      sq.dataset.square = name;
      sq.setAttribute("role", "button");
      sq.tabIndex = 0;

      const ch = pieces[name];
      if (ch) {
        const white = ch === ch.toUpperCase();
        const span = document.createElement("span");
        span.className = "piece " + (white ? "white" : "black");
        span.textContent = PIECE_GLYPH[ch];
        sq.appendChild(span);
        sq.setAttribute("aria-label",
          `${name}, ${white ? "white" : "black"} ${PIECE_NAME[ch.toLowerCase()]}`);
      } else {
        sq.setAttribute("aria-label", name);
      }
      if (rIdx === 7) sq.appendChild(coord("file", file));
      if (fIdx === 0) sq.appendChild(coord("rank", String(rank)));

      sq.addEventListener("click", () => selectSquare(name));
      sq.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); selectSquare(name); }
      });

      board.appendChild(sq);
    });
  });

  if (node.last_move) {
    markSquare(node.last_move.from, "hl-last");
    markSquare(node.last_move.to, "hl-last");
  }
  if (node.in_check) {
    const kc = node.turn === "w" ? "K" : "k";
    for (const [name, ch] of Object.entries(pieces)) {
      if (ch === kc) markSquare(name, "hl-check");
    }
  }
  if (state.selected) {
    markSquare(state.selected, "hl-sel");
    legalFrom(state.selected).forEach((m) => markSquare(m.to, "hl-dest"));
  }
  if (state.pinned) {
    reapplyPin();
  }
}

function renderNav() {
  const n = lastCursor();
  $("nav-counter").textContent = `ply ${state.cursor} / ${n}`;
  $("nav-start").disabled = state.cursor === 0;
  $("nav-prev").disabled = state.cursor === 0;
  $("nav-next").disabled = state.cursor === n;
  $("nav-end").disabled = state.cursor === n;
  $("takeback").disabled = state.moves.length === 0;
}

/* ---------- CCT panels ---------- */

const COLOR_NAME = { w: "White", b: "Black" };

function renderPanels() {
  const node = currentNode();
  renderSidePanel("w", node.cct.w);
  renderSidePanel("b", node.cct.b);
}

function renderSidePanel(color, side) {
  const panel = $("panel-" + color);
  panel.classList.toggle("to-move", side.to_move);
  panel.querySelector(".cct-side-role").textContent = side.to_move ? "to move" : "waiting";

  const body = panel.querySelector(".cct-side-body");
  const unavail = panel.querySelector(".cct-unavailable");

  if (!side.available) {
    body.hidden = true;
    unavail.hidden = false;
    const other = COLOR_NAME[color === "w" ? "b" : "w"];
    unavail.textContent =
      `No plan for ${COLOR_NAME[color]} — ${other} is to move and in check.`;
    setBadges(panel, null);
    return;
  }

  body.hidden = false;
  unavail.hidden = true;
  const r = side.report;
  setBadges(panel, r.counts);

  ["checks", "captures", "threats"].forEach((kind) => {
    const section = panel.querySelector(`.cct-section[data-kind="${kind}"]`);
    const ul = section.querySelector(".candidate-list");
    const trunc = section.querySelector(".cct-truncated");
    ul.innerHTML = "";

    const list = r[kind];
    if (!list.length) {
      const li = document.createElement("li");
      li.className = "cct-empty-dash";
      li.textContent = "—";
      ul.appendChild(li);
    } else {
      list.forEach((c) => ul.appendChild(candidateRow(c, kind, color, side.to_move)));
    }

    if (r.truncated[kind]) {
      trunc.hidden = false;
      trunc.textContent = `showing ${list.length} of ${r.counts[kind]}`;
    } else {
      trunc.hidden = true;
    }
  });
}

function setBadges(panel, counts) {
  const map = { checks: "C", captures: "P", threats: "T" };
  panel.querySelectorAll(".cct-badge").forEach((b) => {
    const k = b.dataset.b;
    b.textContent = map[k] + (counts ? counts[k] : 0);
  });
}

function candidateRow(c, kind, color, sideToMove) {
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

  const playable = sideToMove && atTip() && !currentNode().is_game_over;
  if (playable) li.classList.add("playable");

  const enter = () => highlightCandidate(c, kind);
  const leave = () => { if (!state.pinned) clearCandMarks(); };
  li.addEventListener("mouseenter", enter);
  li.addEventListener("mouseleave", leave);
  li.addEventListener("focus", enter);
  li.addEventListener("blur", leave);
  li.addEventListener("click", () => {
    if (playable) {
      playMove(c.uci);
    } else {
      togglePin(c, kind, color);
    }
  });
  if (state.pinned && state.pinned.uci === c.uci && state.pinned.color === color) {
    li.classList.add("pinned");
  }
  return li;
}

function clearCandMarks() {
  clearMarks("hl-cand-from");
  clearMarks("hl-cand-to");
  clearMarks("hl-gain");
}

function highlightCandidate(c, kind) {
  clearCandMarks();
  markSquare(c.from, "hl-cand-from");
  markSquare(c.to, "hl-cand-to");
  if (kind === "threats" && c.gains.length) {
    const g = c.gains[0];
    if (g.square) markSquare(g.square, "hl-gain");
    (g.targets || []).forEach((t) => markSquare(t, "hl-gain"));
  }
}

function togglePin(c, kind, color) {
  if (state.pinned && state.pinned.uci === c.uci && state.pinned.color === color) {
    state.pinned = null;
    clearCandMarks();
  } else {
    state.pinned = { uci: c.uci, color, kind };
  }
  renderAll();
}

function reapplyPin() {
  const side = currentNode().cct[state.pinned.color];
  if (!side.available) { state.pinned = null; return; }
  const list = side.report[state.pinned.kind] || [];
  const c = list.find((x) => x.uci === state.pinned.uci);
  if (c) highlightCandidate(c, state.pinned.kind);
  else state.pinned = null;
}

/* ---------- Move list ---------- */

function renderMoveList() {
  const wrap = $("moves");
  wrap.innerHTML = "";
  const nodes = state.nodes;

  let row = 0;
  for (let i = 1; i < nodes.length; i++) {
    const n = nodes[i];
    const isWhiteMove = n.turn === "b"; // the move that produced a black-to-move pos was White's
    if (isWhiteMove) {
      const num = document.createElement("span");
      num.className = "move-num";
      num.textContent = n.move_number + ".";
      wrap.appendChild(num);
      wrap.appendChild(moveCell(i));
      // placeholder for a possible black move; filled by the next iteration
      row++;
    } else {
      if (row === 0) {
        // line starts with a Black move (FEN game): number + gap + move
        const num = document.createElement("span");
        num.className = "move-num";
        num.textContent = n.move_number + "...";
        wrap.appendChild(num);
        const gap = document.createElement("span");
        gap.className = "move move-gap";
        gap.textContent = "…";
        wrap.appendChild(gap);
        row++;
      }
      wrap.appendChild(moveCell(i));
    }
  }

  const cur = wrap.querySelector(`.move[data-index="${state.cursor}"]`);
  if (cur) { cur.classList.add("current"); cur.scrollIntoView({ block: "nearest" }); }
}

function moveCell(index) {
  const span = document.createElement("span");
  span.className = "move";
  span.dataset.index = String(index);
  span.textContent = state.nodes[index].san;
  span.addEventListener("click", () => goto(index));
  return span;
}

/* ---------- Status bar ---------- */

function gameOverText(node) {
  const reason = node.over_reason ? node.over_reason.replace(/_/g, " ") : "game over";
  return `Game over — ${reason}${node.result ? " (" + node.result + ")" : ""}.`;
}

function renderStatus() {
  const node = currentNode();
  if (node.is_game_over) { setStatus(gameOverText(node)); return; }
  const stm = node.cct[node.turn];
  const c = stm.available ? stm.report.counts : { checks: 0, captures: 0, threats: 0 };
  setStatus(
    `${COLOR_NAME[node.turn]} to move — ${c.checks} checks, ${c.captures} captures, ${c.threats} threats`
  );
}
function setStatus(text) {
  $("status").textContent = text;
}

/* ------------------------------------------------------------------ */
/* Error banner                                                       */
/* ------------------------------------------------------------------ */

function showError(msg) {
  const el = $("play-error");
  el.textContent = msg;
  el.hidden = false;
}
function hideError() {
  $("play-error").hidden = true;
}

/* ------------------------------------------------------------------ */
/* New game / FEN                                                     */
/* ------------------------------------------------------------------ */

async function newGame() {
  if (state.moves.length > 0 && !confirm("Start a new game? The current line will be lost.")) return;
  state.startFen = null;
  state.moves = [];
  state.cursor = 0;
  try {
    await refetchAll();
  } catch (err) {
    showError(err.message);
  }
}

async function setFen() {
  const fen = prompt("Start position FEN:");
  if (fen === null) return;
  const prev = { startFen: state.startFen, moves: state.moves.slice(), nodes: state.nodes.slice(), cursor: state.cursor };
  state.startFen = fen.trim() || null;
  state.moves = [];
  state.cursor = 0;
  try {
    await refetchAll();
  } catch (err) {
    Object.assign(state, prev);   // keep the current game (spec 9.5)
    showError(err.message);
    renderAll();
  }
}

/* ------------------------------------------------------------------ */
/* Persistence (spec 9.6)                                             */
/* ------------------------------------------------------------------ */

function persist() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      startFen: state.startFen,
      moves: state.moves,
      cursor: state.cursor,
      flipped: state.flipped,
    }));
  } catch (e) { /* ignore */ }
}

async function restoreOrStart() {
  let saved = null;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) saved = JSON.parse(raw);
  } catch (e) { saved = null; }

  if (saved && Array.isArray(saved.moves)) {
    state.startFen = saved.startFen || null;
    state.moves = saved.moves.slice();
    state.cursor = Number.isInteger(saved.cursor) ? saved.cursor : saved.moves.length;
    state.flipped = !!saved.flipped;
    try {
      await refetchAll();
      return;
    } catch (e) {
      try { localStorage.removeItem(STORAGE_KEY); } catch (_) { /* ignore */ }
    }
  }
  state.startFen = null;
  state.moves = [];
  state.cursor = 0;
  try {
    await refetchAll();
  } catch (err) {
    showError("Could not reach the server: " + err.message);
  }
}

/* ------------------------------------------------------------------ */
/* Copy PGN (spec 9.7)                                                */
/* ------------------------------------------------------------------ */

function buildPgn() {
  const nodes = state.nodes;
  const last = nodes[nodes.length - 1];
  const result = last && last.result ? last.result : "*";
  const now = new Date();
  const date = `${now.getFullYear()}.${String(now.getMonth() + 1).padStart(2, "0")}.${String(now.getDate()).padStart(2, "0")}`;

  const lines = [
    '[Event "CCT Viz Play"]',
    '[Site "CCT Viz"]',
    `[Date "${date}"]`,
    '[Round "-"]',
    '[White "Player"]',
    '[Black "Player"]',
    `[Result "${result}"]`,
  ];
  const startFen = state.startFen && state.nodes[0] ? state.nodes[0].fen : null;
  if (startFen && startFen !== START_FEN) {
    lines.push('[SetUp "1"]');
    lines.push(`[FEN "${startFen}"]`);
  }

  const tokens = [];
  for (let i = 1; i < nodes.length; i++) {
    const n = nodes[i];
    const whiteMoved = n.turn === "b";
    if (whiteMoved) {
      tokens.push(`${n.move_number}.`);
    } else if (i === 1) {
      tokens.push(`${n.move_number}...`);
    }
    tokens.push(n.san);
  }
  tokens.push(result);

  let movetext = "";
  let lineLen = 0;
  for (const t of tokens) {
    const add = (lineLen === 0 ? "" : " ") + t;
    if (lineLen + add.length > 80) {
      movetext += "\n" + t;
      lineLen = t.length;
    } else {
      movetext += add;
      lineLen += add.length;
    }
  }

  return lines.join("\n") + "\n\n" + movetext + "\n";
}

async function copyPgn() {
  const pgn = buildPgn();
  let ok = false;
  try {
    await navigator.clipboard.writeText(pgn);
    ok = true;
  } catch (e) {
    const sink = $("pgn-copy-sink");
    sink.value = pgn;
    sink.select();
    try { ok = document.execCommand("copy"); } catch (_) { ok = false; }
    sink.blur();
  }
  setStatus(ok ? "PGN copied to clipboard." : "Could not copy PGN.");
}

/* ------------------------------------------------------------------ */
/* Wiring                                                             */
/* ------------------------------------------------------------------ */

function init() {
  $("nav-start").addEventListener("click", () => goto(0));
  $("nav-prev").addEventListener("click", () => goto(state.cursor - 1));
  $("nav-next").addEventListener("click", () => goto(state.cursor + 1));
  $("nav-end").addEventListener("click", () => goto(lastCursor()));
  $("nav-flip").addEventListener("click", flip);
  $("takeback").addEventListener("click", takeback);
  $("btn-new").addEventListener("click", newGame);
  $("btn-fen").addEventListener("click", setFen);
  $("btn-pgn").addEventListener("click", copyPgn);

  restoreOrStart();
}

init();
