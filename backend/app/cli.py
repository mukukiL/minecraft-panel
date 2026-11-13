import argparse
import getpass
import sys
import warnings

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select

from app.auth import Username, audit, hash_password
from app.config import load_settings
from app.db import User, database, write
from app.errors import Problem


def main() -> int:
    parser = argparse.ArgumentParser(description="Minecraft Panel administrator initialization")
    parser.add_argument("command", choices=["create-admin"])
    args = parser.parse_args()
    if args.command == "create-admin" and not sys.stdin.isatty():
        parser.exit(1, "Run this command in an interactive terminal.\n")
    try:
        username = TypeAdapter(Username).validate_python(input("Username: ")).lower()
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = getpass.getpass("Password: ")
            if password != getpass.getpass("Repeat password: "):
                raise Problem(422, "PASSWORD_MISMATCH")
        encoded = hash_password(username, password)
        engine = database(load_settings().db_path)
        try:
            with write(engine) as db:
                if db.scalar(select(User.id).limit(1)) is not None:
                    raise Problem(409, "BOOTSTRAP_ALREADY_COMPLETED")
                user = User(username=username, password_hash=encoded, role="admin", enabled=True)
                db.add(user)
                db.flush()
                audit(db, "admin.bootstrap", user.id)
        finally:
            engine.dispose()
    except ValidationError:
        parser.exit(1, "Invalid username.\n")
    except Problem as exc:
        parser.exit(1, exc.code + "\n")
    except getpass.GetPassWarning:
        parser.exit(1, "This terminal cannot hide password input.\n")
    print("Initial administrator created.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
