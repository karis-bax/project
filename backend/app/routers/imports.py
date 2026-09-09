"""CSV import: two-step preview then commit. Nothing is written until commit."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import importer, schemas
from ..deps import get_db
from ..models import Account, CategoryRule, Transaction, TxnSource
from ..rules_engine import Rule, propose_category, sort_rules

router = APIRouter(prefix="/api/import", tags=["import"])


@dataclass
class StagedBatch:
    account_id: int
    header: list[str] | None
    data_rows: list[list[str]]
    delimiter: str
    has_header: bool
    created_at: float


# In-memory staging store keyed by opaque token. Fine for a single-process app;
# nothing here is written to the database until /commit.
_STAGED: dict[str, StagedBatch] = {}
_STAGE_TTL_SECONDS = 60 * 60


def _prune() -> None:
    cutoff = time.time() - _STAGE_TTL_SECONDS
    for token in [t for t, b in _STAGED.items() if b.created_at < cutoff]:
        _STAGED.pop(token, None)


def _load_rules(db: Session) -> list[Rule]:
    rules = db.scalars(select(CategoryRule)).all()
    return sort_rules(
        [
            Rule(
                match_field=r.match_field.value,
                pattern=r.pattern,
                category_id=r.category_id,
                priority=r.priority,
            )
            for r in rules
        ]
    )


def _existing_hashes(db: Session) -> set[str]:
    return {
        h
        for h in db.scalars(
            select(Transaction.import_hash).where(Transaction.import_hash.is_not(None))
        )
    }


def _soft_deleted_by_hash(db: Session) -> dict[str, Transaction]:
    """Soft-deleted rows keyed by import_hash — candidates to REVIVE so a
    previously-deleted transaction can come back on re-import."""

    rows = db.scalars(
        select(Transaction)
        .where(Transaction.import_hash.is_not(None))
        .where(Transaction.deleted_at.is_not(None))
        .execution_options(include_deleted=True)
    )
    return {t.import_hash: t for t in rows if t.import_hash}


def _columns(batch: StagedBatch) -> list[str]:
    if batch.header:
        return batch.header
    width = max((len(r) for r in batch.data_rows), default=0)
    return [f"Column {i + 1}" for i in range(width)]


def _build_rows(
    batch: StagedBatch,
    mapping: importer.Mapping,
    db: Session,
) -> tuple[list[schemas.ImportPreviewRow], list[str]]:
    parsed, warnings = importer.parse_rows(batch.data_rows, mapping)
    rules = _load_rules(db)
    existing = _existing_hashes(db)
    seen: set[str] = set()

    rows: list[schemas.ImportPreviewRow] = []
    for p in parsed:
        import_hash: str | None = None
        is_duplicate = False
        if p.importable and p.date is not None and p.amount_cents is not None:
            import_hash = importer.compute_import_hash(
                batch.account_id, p.date, p.amount_cents, p.payee
            )
            is_duplicate = import_hash in existing or import_hash in seen
            seen.add(import_hash)
        proposed = propose_category(rules, p.payee, p.memo)
        rows.append(
            schemas.ImportPreviewRow(
                row_index=p.row_index,
                date=p.date,
                payee=p.payee,
                amount_cents=p.amount_cents,
                memo=p.memo,
                proposed_category_id=proposed,
                is_duplicate=is_duplicate,
                importable=p.importable,
                import_hash=import_hash,
                warnings=p.warnings,
            )
        )
    return rows, warnings


def _response(
    token: str, batch: StagedBatch, mapping: importer.Mapping, db: Session
) -> schemas.ImportPreviewResponse:
    rows, warnings = _build_rows(batch, mapping, db)
    return schemas.ImportPreviewResponse(
        token=token,
        account_id=batch.account_id,
        delimiter=batch.delimiter,
        has_header=batch.has_header,
        columns=_columns(batch),
        mapping=schemas.ImportMapping(**vars(mapping)),
        raw_sample=batch.data_rows[:5],
        rows=rows,
        warnings=warnings,
    )


@router.post("/preview", response_model=schemas.ImportPreviewResponse)
async def preview_import(
    account_id: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> schemas.ImportPreviewResponse:
    if db.get(Account, account_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Account {account_id} not found.",
        )

    raw = await file.read()
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        content = raw.decode("latin-1")

    delimiter, has_header = importer.sniff(content)
    all_rows = importer.read_rows(content, delimiter)
    if not all_rows:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The file appears to be empty.",
        )

    header = all_rows[0] if has_header else None
    data_rows = all_rows[1:] if has_header else all_rows

    _prune()
    token = secrets.token_urlsafe(16)
    batch = StagedBatch(
        account_id=account_id,
        header=header,
        data_rows=data_rows,
        delimiter=delimiter,
        has_header=has_header,
        created_at=time.time(),
    )
    _STAGED[token] = batch

    mapping = importer.propose_mapping(header, data_rows)
    return _response(token, batch, mapping, db)


@router.post("/remap", response_model=schemas.ImportPreviewResponse)
def remap_import(
    payload: schemas.ImportRemapRequest, db: Session = Depends(get_db)
) -> schemas.ImportPreviewResponse:
    batch = _STAGED.get(payload.token)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unknown or expired import token; re-upload the file.",
        )
    mapping = importer.Mapping(**payload.mapping.model_dump())
    return _response(payload.token, batch, mapping, db)


@router.post("/commit", response_model=schemas.ImportCommitResponse)
def commit_import(
    payload: schemas.ImportCommitRequest, db: Session = Depends(get_db)
) -> schemas.ImportCommitResponse:
    batch = _STAGED.get(payload.token)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unknown or expired import token; re-upload the file.",
        )
    account_id = batch.account_id

    existing = _existing_hashes(db)
    revivable = _soft_deleted_by_hash(db)
    seen: set[str] = set()
    imported = skipped_duplicate = failed = 0
    to_add: list[Transaction] = []

    for row in payload.rows:
        try:
            import_hash = importer.compute_import_hash(
                account_id, row.date, row.amount_cents, row.payee
            )
        except Exception:  # noqa: BLE001 - a bad row must not abort the batch
            failed += 1
            continue

        # Idempotent on import_hash regardless of the skip flag.
        if import_hash in existing or import_hash in seen:
            skipped_duplicate += 1
            continue

        try:
            parsed_date = date.fromisoformat(row.date)
        except ValueError:
            failed += 1
            continue

        # Revive a previously soft-deleted row instead of inserting (and instead
        # of the unique constraint blocking it forever).
        revived = revivable.pop(import_hash, None)
        if revived is not None:
            revived.deleted_at = None
            revived.category_id = row.category_id
            revived.date = parsed_date
            revived.payee = row.payee
            revived.amount_cents = row.amount_cents
            revived.memo = row.memo
            revived.source = TxnSource.csv
            seen.add(import_hash)
            imported += 1
            continue

        if payload.skip_duplicates and row.is_duplicate:
            skipped_duplicate += 1
            continue

        to_add.append(
            Transaction(
                account_id=account_id,
                category_id=row.category_id,
                date=parsed_date,
                payee=row.payee,
                amount_cents=row.amount_cents,
                memo=row.memo,
                cleared=False,
                source=TxnSource.csv,
                import_hash=import_hash,
            )
        )
        seen.add(import_hash)
        imported += 1

    # Single transaction for the whole batch.
    db.add_all(to_add)
    db.commit()
    _STAGED.pop(payload.token, None)

    return schemas.ImportCommitResponse(
        imported=imported, skipped_duplicate=skipped_duplicate, failed=failed
    )
