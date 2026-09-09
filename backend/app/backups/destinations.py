"""Where encrypted backup artifacts are stored.

Two destinations, selected by ``BACKUP_DEST``: ``local`` (default) and ``s3``
(any S3-compatible endpoint — B2, R2, MinIO — via ``BACKUP_S3_ENDPOINT_URL``).

Artifacts are already encrypted before they reach a destination, so a
destination never handles plaintext and never needs the age keys.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Protocol


class Destination(Protocol):
    """Somewhere encrypted artifacts can be put, listed, fetched and removed."""

    def upload(self, local_path: Path, name: str) -> None: ...
    def download(self, name: str, local_path: Path) -> None: ...
    def list_names(self) -> list[str]: ...
    def delete(self, name: str) -> None: ...
    def describe(self) -> str: ...


class LocalDestination:
    """A directory on this machine or a mounted volume.

    Fine for an external disk; it is NOT off-host, so it does not protect
    against losing the machine. Prefer s3 for the real copy.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def upload(self, local_path: Path, name: str) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local_path, self.directory / name)

    def download(self, name: str, local_path: Path) -> None:
        shutil.copyfile(self.directory / name, local_path)

    def list_names(self) -> list[str]:
        if not self.directory.exists():
            return []
        return [p.name for p in self.directory.iterdir() if p.is_file()]

    def delete(self, name: str) -> None:
        (self.directory / name).unlink(missing_ok=True)

    def describe(self) -> str:
        return f"local:{self.directory}"


class S3Destination:
    """Any S3-compatible object store.

    boto3 is imported lazily so the local destination — and the test suite —
    work without it installed.
    """

    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        endpoint_url: str | None = None,
        region: str | None = None,
    ) -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.endpoint_url = endpoint_url
        self.region = region
        self._client_cache = None

    def _key(self, name: str) -> str:
        return f"{self.prefix}/{name}" if self.prefix else name

    def _client(self):
        if self._client_cache is None:
            try:
                import boto3
            except ImportError as exc:  # pragma: no cover - depends on env
                raise RuntimeError(
                    "BACKUP_DEST=s3 requires boto3 (uv add boto3)."
                ) from exc
            self._client_cache = boto3.client(
                "s3", endpoint_url=self.endpoint_url, region_name=self.region
            )
        return self._client_cache

    def upload(self, local_path: Path, name: str) -> None:
        self._client().upload_file(str(local_path), self.bucket, self._key(name))

    def download(self, name: str, local_path: Path) -> None:
        self._client().download_file(self.bucket, self._key(name), str(local_path))

    def list_names(self) -> list[str]:
        paginator = self._client().get_paginator("list_objects_v2")
        names: list[str] = []
        for page in paginator.paginate(
            Bucket=self.bucket, Prefix=f"{self.prefix}/" if self.prefix else ""
        ):
            for obj in page.get("Contents", []):
                names.append(obj["Key"].rsplit("/", 1)[-1])
        return names

    def delete(self, name: str) -> None:
        self._client().delete_object(Bucket=self.bucket, Key=self._key(name))

    def describe(self) -> str:
        target = f"s3://{self.bucket}/{self.prefix}".rstrip("/")
        return f"{target} @ {self.endpoint_url}" if self.endpoint_url else target


def destination_from_env(env: dict[str, str] | None = None) -> Destination:
    """Build the configured destination. Unknown BACKUP_DEST is an error, not a
    silent fallback to local — a typo must not quietly write backups to disk
    when they were meant to go off-host."""

    env = dict(os.environ) if env is None else env
    kind = (env.get("BACKUP_DEST") or "local").strip().lower()

    if kind == "local":
        directory = env.get("BACKUP_LOCAL_DIR") or "./backups"
        return LocalDestination(Path(directory).expanduser().resolve())

    if kind == "s3":
        bucket = env.get("BACKUP_S3_BUCKET")
        if not bucket:
            raise RuntimeError("BACKUP_DEST=s3 requires BACKUP_S3_BUCKET.")
        return S3Destination(
            bucket=bucket,
            prefix=env.get("BACKUP_S3_PREFIX", ""),
            endpoint_url=env.get("BACKUP_S3_ENDPOINT_URL") or None,
            region=env.get("BACKUP_S3_REGION") or None,
        )

    raise RuntimeError(
        f"Unknown BACKUP_DEST {kind!r}; expected 'local' or 's3'."
    )
