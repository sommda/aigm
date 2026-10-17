"""`aigm` command: run the server (optionally in scripted --test mode)."""

import argparse
import os


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="aigm", description="AIGM game master server")
    parser.add_argument("--test", action="store_true", help="scripted test mode: no LLM, canned SSE replies")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--debug", action="store_true", help="debug mode: lets a client inspect the full model context (shows spoilers)"
    )
    parser.add_argument("--reload", action="store_true", help="auto-reload on code changes (dev)")
    args = parser.parse_args(argv)

    if args.test:
        os.environ["AIGM_TEST_MODE"] = "true"
    if args.debug:
        os.environ["AIGM_DEBUG"] = "true"
    import uvicorn

    if args.test:
        print("AIGM test mode: replies are scripted (send 'help' for commands); no LLM is used.")
    if args.debug:
        print("AIGM debug mode: GET /debug/context is open and shows hidden game information (GM notes, secrets).")
        if args.host not in ("127.0.0.1", "localhost", "::1"):
            print(f"WARNING: the server listens on {args.host}; anyone who can reach it can read the GM's secrets.")
    uvicorn.run("aigm.app:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
