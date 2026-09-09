"""``python -m cct_viz`` — start the web server."""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(prog="cct_viz", description="CCT Viz server")
    parser.add_argument("--host", default="127.0.0.1", help="bind host (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="bind port (default 8000)")
    args = parser.parse_args()

    import uvicorn

    uvicorn.run("cct_viz.server:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
