import argparse
import os

from adb_automation.api import create_app
from adb_automation.config import (
    API_HOST_ENV_VAR,
    API_PORT_ENV_VAR,
    DEFAULT_API_HOST,
    DEFAULT_API_PORT,
    env_int,
)

app = create_app()


def build_parser():
    parser = argparse.ArgumentParser(description="Run the ADB automation Flask API.")
    parser.add_argument(
        "--host",
        default=os.environ.get(API_HOST_ENV_VAR, DEFAULT_API_HOST),
        help=f"Host to bind. Defaults to ${API_HOST_ENV_VAR} or {DEFAULT_API_HOST}.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=env_int(API_PORT_ENV_VAR, DEFAULT_API_PORT),
        help=f"Port to bind. Defaults to ${API_PORT_ENV_VAR} or {DEFAULT_API_PORT}.",
    )
    return parser


if __name__ == "__main__":
    args = build_parser().parse_args()
    app.run(host=args.host, port=args.port)
