"""age encryption for backup artifacts.

The recipient is a PUBLIC key, so the backup host can encrypt but cannot read
what it wrote. The private identity lives where the restore drill runs — off
this host. That asymmetry is the point: a compromised backup host leaks no
financial history.

Shells out to the ``age`` binary rather than binding a library so the artifacts
are decryptable with the standard tool by a human with the identity file and no
Python environment at all.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class AgeError(RuntimeError):
    """age is missing, or an encrypt/decrypt invocation failed."""


def _age_binary() -> str:
    binary = shutil.which("age")
    if binary is None:
        raise AgeError(
            "The `age` binary is not on PATH. Install it (brew install age) — "
            "refusing to write an unencrypted backup."
        )
    return binary


def _run(args: list[str]) -> None:
    try:
        result = subprocess.run(args, capture_output=True, check=False)
    except OSError as exc:
        raise AgeError(f"Could not run age: {exc}") from exc
    if result.returncode != 0:
        # stderr may name paths but never key material; age does not echo keys.
        detail = result.stderr.decode("utf-8", "replace").strip() or "no output"
        raise AgeError(f"age exited {result.returncode}: {detail}")


def encrypt(source: Path, target: Path, recipient: str) -> None:
    """Encrypt ``source`` to ``target`` for ``recipient`` (an age public key)."""

    if not recipient:
        raise AgeError("No age recipient given; refusing to write plaintext.")
    _run([_age_binary(), "--encrypt", "--recipient", recipient,
          "--output", str(target), str(source)])
    if not target.exists() or target.stat().st_size == 0:
        raise AgeError(f"age produced no output at {target}.")


def decrypt(source: Path, target: Path, identity: Path) -> None:
    """Decrypt ``source`` to ``target`` using the age identity file."""

    if not identity.exists():
        raise AgeError(f"age identity file not found: {identity}")
    _run([_age_binary(), "--decrypt", "--identity", str(identity),
          "--output", str(target), str(source)])
    if not target.exists():
        raise AgeError(f"age produced no output at {target}.")
