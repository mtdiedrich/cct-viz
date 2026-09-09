"""FastAPI app: serves the JSON API and the static frontend (spec section 5)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
from .pgn import PgnError, build_game_response

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="CCT Viz", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


class GameRequest(BaseModel):
    pgn: str | None = None
    game_index: int = 0


@app.exception_handler(PgnError)
async def _pgn_error_handler(request: Request, exc: PgnError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html", media_type="text/html")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.post("/api/game")
def post_game(req: GameRequest):
    return build_game_response(req.pgn, req.game_index)
