#!/usr/bin/env python
"""Move the pre-multi-user SimpleFIN access URL into a user's keyring slot.

Alembic cannot touch the OS keyring, so this is a separate one-off step. The
old layout stored a single entry under the username "access-url"; credentials
are now keyed per user.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.sync.credentials import _SERVICE, _username, store_access_url  # noqa: E402

_LEGACY_USERNAME = "access-url"


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        print(f"usage: {sys.argv[0]} <user_id>", file=sys.stderr)
        return 2
    user_id = int(sys.argv[1])

    try:
        import keyring
    except ImportError:
        print("keyring is not installed.", file=sys.stderr)
        return 1

    legacy = keyring.get_password(_SERVICE, _LEGACY_USERNAME)
    if not legacy:
        print("No legacy access URL found; nothing to migrate.")
        return 0

    store_access_url(user_id, legacy)
    keyring.delete_password(_SERVICE, _LEGACY_USERNAME)
    # Never print the URL itself: it is a read key to the whole account.
    print(f"Moved the SimpleFIN access URL to {_username(user_id)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
