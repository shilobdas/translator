import argparse
import getpass
import sys

from .admin_tools import create_or_update_admin


def read_password(password_stdin: bool) -> str:
    if password_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    password = getpass.getpass("Admin password: ")
    confirm_password = getpass.getpass("Confirm admin password: ")
    if password != confirm_password:
        raise ValueError("Passwords do not match.")
    return password


def create_admin_command(args) -> int:
    password = read_password(args.password_stdin)
    result = create_or_update_admin(args.username, password)
    print(f"Admin user {result.action}: {result.username}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Translator App management commands")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_admin = subparsers.add_parser(
        "create-admin",
        help="Create or reset an admin user in the configured database.",
    )
    create_admin.add_argument("--username", required=True, help="Admin username")
    create_admin.add_argument(
        "--password-stdin",
        action="store_true",
        help="Read the password from stdin. Prefer the interactive prompt for manual use.",
    )
    create_admin.set_defaults(func=create_admin_command)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
