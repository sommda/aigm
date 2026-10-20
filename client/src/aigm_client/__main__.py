import argparse
import os

from aigm_client.api import DEFAULT_URL, ApiClient
from aigm_client.app import AigmApp


def main() -> None:
    parser = argparse.ArgumentParser(prog="aigm-client", description="Terminal client for the AIGM server")
    parser.add_argument("--url", default=os.environ.get("AIGM_URL", DEFAULT_URL))
    parser.add_argument("--session", default="default", help="server session id")
    parser.add_argument(
        "--no-mouse",
        action="store_true",
        help="leave the mouse to the terminal, so text can be selected and copied (the wheel stops scrolling)",
    )
    parser.add_argument("--ascii", action="store_true", help="avoid emoji in dice output")
    args = parser.parse_args()
    AigmApp(ApiClient(args.url, args.session), ascii_only=args.ascii).run(mouse=not args.no_mouse)


if __name__ == "__main__":
    main()
