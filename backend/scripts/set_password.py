#!/usr/bin/env python
"""Set a user's password interactively.

The bootstrap user created by migration f3a1c7b90e21 has a hash nothing can
match, so this is how it becomes usable. Interactive rather than an env var or
an argument: a password passed either of those ways lands in shell history,
`ps` output, and any captured log.
"""

from __future__ import annotations

import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select  # noqa: E402

from app.auth.security import hash_password, normalize_email  # noqa: E402
from app.db import unscoped_session  # noqa: E402
from app.models import User  # noqa: E402

MIN_LENGTH = 12


def main() -> int:
    with unscoped_session(
        reason="setting a password must find the user before any scope exists"
    ) as db:
        users = list(db.scalars(select(User).order_by(User.id)))
        if not users:
            print(
                "No users exist. Run `just migrate` with BOOTSTRAP_EMAIL set.",
                file=sys.stderr,
            )
            return 1

        if len(users) == 1:
            user = users[0]
            print(f"Setting the password for {user.email}.")
        else:
            for u in users:
                print(f"  {u.id}: {u.email}")
            raw = input("User id: ").strip()
            if not raw.isdigit():
                print("Not a number.", file=sys.stderr)
                return 1
            user = db.scalar(select(User).where(User.id == int(raw)))
            if user is None:
                print("No such user.", file=sys.stderr)
                return 1

        password = getpass.getpass("New password: ")
        if len(password) < MIN_LENGTH:
            print(f"Too short (minimum {MIN_LENGTH} characters).", file=sys.stderr)
            return 1
        if password != getpass.getpass("Repeat: "):
            print("Passwords did not match.", file=sys.stderr)
            return 1

        user.password_hash = hash_password(password)
        db.commit()

    print(f"Password set for {normalize_email(user.email)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
