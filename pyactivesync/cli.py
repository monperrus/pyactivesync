"""``pyactivesync`` console script: list-folders, sync, send, fetch, ping."""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from email.message import EmailMessage

from .client import Client
from .exceptions import EASError
from .models import BodyType


def _client_from_args(args: argparse.Namespace) -> Client:
    password = args.password or os.environ.get("PYACTIVESYNC_PASSWORD")
    if not password:
        raise SystemExit("no password: pass --password or set PYACTIVESYNC_PASSWORD")
    return Client(
        args.server,
        args.username,
        password,
        device_id=args.device_id,
        user=args.user,
    )


def _to_jsonable(obj: object) -> object:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if isinstance(obj, list):
        return [_to_jsonable(o) for o in obj]
    return obj


def _print(obj: object, as_json: bool) -> None:
    if as_json:
        print(json.dumps(_to_jsonable(obj), default=str, indent=2))
    else:
        print(obj)


def _add_common_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--server", required=True, help="EAS server hostname")
    p.add_argument("--username", required=True, help="auth username (domain\\user or email)")
    p.add_argument("--user", help="mailbox SMTP address for the User param (defaults to --username)")
    p.add_argument("--password", help="password (falls back to PYACTIVESYNC_PASSWORD env var)")
    p.add_argument("--device-id", default="pyactivesync-cli", help="device id (default: pyactivesync-cli)")
    p.add_argument("--json", action="store_true", help="output JSON instead of a table")


def cmd_list_folders(args: argparse.Namespace) -> None:
    with _client_from_args(args) as client:
        folders = client.list_folders()
        if args.json:
            _print(folders, True)
            return
        for f in folders:
            print(f"{f.id}\t{f.type.name}\t{f.parent_id}\t{f.name}")


def cmd_sync(args: argparse.Namespace) -> None:
    with _client_from_args(args) as client:
        result = client.sync_folder(args.folder_id, sync_key=args.sync_key, window_size=args.window_size)
        if args.json:
            _print(result, True)
            return
        print(f"SyncKey={result.sync_key} more_available={result.more_available}")
        for item in result.added:
            print(f"  + {item.server_id}\t{item.fields}")
        for item in result.changed:
            print(f"  ~ {item.server_id}\t{item.fields}")
        for server_id in result.deleted:
            print(f"  - {server_id}")


def cmd_fetch(args: argparse.Namespace) -> None:
    with _client_from_args(args) as client:
        body_type = BodyType[args.body_type.upper()]
        props = client.fetch_item(args.folder_id, args.item_id, body_type=body_type)
        _print(props, args.json)


def cmd_send(args: argparse.Namespace) -> None:
    msg = EmailMessage()
    msg["To"] = args.to
    msg["From"] = args.user or args.username
    msg["Subject"] = args.subject
    msg.set_content(args.body)
    with _client_from_args(args) as client:
        client.send_mail(msg)
    if not args.json:
        print("sent")


def cmd_ping(args: argparse.Namespace) -> None:
    with _client_from_args(args) as client:
        result = client.ping(args.folder_ids, heartbeat=args.heartbeat, timeout=args.timeout)
        _print(result, args.json)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pyactivesync", description="Exchange ActiveSync client CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list-folders", help="list the folder hierarchy")
    _add_common_args(p)
    p.set_defaults(func=cmd_list_folders)

    p = sub.add_parser("sync", help="sync one folder")
    _add_common_args(p)
    p.add_argument("folder_id")
    p.add_argument("--sync-key", default="0")
    p.add_argument("--window-size", type=int, default=25)
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("fetch", help="fetch one item's properties")
    _add_common_args(p)
    p.add_argument("folder_id")
    p.add_argument("item_id")
    p.add_argument("--body-type", default="html", choices=["plain_text", "html", "rtf", "mime"])
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("send", help="send a plain-text message")
    _add_common_args(p)
    p.add_argument("--to", required=True)
    p.add_argument("--subject", required=True)
    p.add_argument("--body", required=True)
    p.set_defaults(func=cmd_send)

    p = sub.add_parser("ping", help="long-poll one or more folders for changes")
    _add_common_args(p)
    p.add_argument("folder_ids", nargs="+")
    p.add_argument("--heartbeat", type=int, default=60)
    p.add_argument("--timeout", type=float, default=30.0)
    p.set_defaults(func=cmd_ping)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except EASError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
