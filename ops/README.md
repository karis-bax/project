# Envelope operations: backups & restore drills

## What runs

- **Backup** (`just backup` → `backend/scripts/backup.py`): `VACUUM INTO` a
  consistent snapshot, gzip, encrypt with [`age`](https://age-encryption.org) to
  a recipient whose **private key is not on this host**, upload to the configured
  destination, apply 7-daily / 4-weekly / 12-monthly retention, write a JSON
  status file. Exits non-zero and fires an alert on any failure.
- **Restore drill** (`just restore-drill` → `backend/scripts/restore_drill.py`):
  pull the latest artifact, decrypt (needs the age identity), decompress,
  `PRAGMA integrity_check`, and compare table set + per-table row counts (±5%) +
  a non-zero `sum(amount_cents)` against the live DB.
- **Purge** (`just purge`): hard-delete rows soft-deleted more than 90 days ago.
  Schedule it alongside the backup.

Never `cp` the live SQLite file — a copy taken mid-write can capture a torn page
or a half-applied transaction. `VACUUM INTO` always writes a transactionally
consistent database.

## Environment

| Variable | Purpose |
| --- | --- |
| `BACKUP_AGE_RECIPIENT` | age **public** key to encrypt to (required for backup). |
| `BACKUP_AGE_IDENTITY` | path to the age **private** key (restore drill only; keep off the backup host). |
| `BACKUP_DEST` | `local` (default) or `s3`. |
| `BACKUP_LOCAL_DIR` | destination dir when `BACKUP_DEST=local`. |
| `BACKUP_S3_BUCKET` / `BACKUP_S3_PREFIX` / `BACKUP_S3_ENDPOINT_URL` / `BACKUP_S3_REGION` / `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | S3 / B2 / R2 target. |
| `BACKUP_LOG` | alert log path (default `~/.envelope/backup.log`). |

Generate a keypair once (the identity file is the secret; store it off the
backup host):

```bash
age-keygen -o backup_identity.txt      # prints the public key too
```

## Scheduling on macOS (launchd, not cron)

Edit the two plists in `ops/launchd/` (paths, recipient, destination), then:

```bash
cp ops/launchd/com.envelope.backup.plist ~/Library/LaunchAgents/
cp ops/launchd/com.envelope.restore-drill.plist ~/Library/LaunchAgents/

# Load (bootstrap) into the current GUI session (uid 501 shown; use `id -u`):
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.envelope.backup.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.envelope.restore-drill.plist

# Verify:
launchctl list | grep com.envelope

# Run once now (without waiting for the schedule):
launchctl kickstart -k gui/$(id -u)/com.envelope.backup

# Unload (bootout):
launchctl bootout gui/$(id -u)/com.envelope.backup
launchctl bootout gui/$(id -u)/com.envelope.restore-drill
```

These use `StartCalendarInterval` (daily 02:30 backup; Sunday 03:00 drill).
**A sleeping Mac does not skip the job** — launchd runs a missed
`StartCalendarInterval` job once when the machine next wakes.

## Alerting

On backup failure or a failed integrity check, the scripts append to `BACKUP_LOG`
**and** fire an `osascript` desktop notification. A silent backup failure is the
real disaster, so failures are always both logged and surfaced.
