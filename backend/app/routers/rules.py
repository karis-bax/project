"""Category rules: CRUD, reorder by priority, and apply-to-existing."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import schemas
from ..deps import get_db, get_live_or_404, validate_month
from ..models import Category, CategoryRule, Transaction
from ..rules_engine import Rule, propose_category, sort_rules

router = APIRouter(prefix="/api/rules", tags=["rules"])


def _category_or_404(db: Session, category_id: int) -> Category:
    return get_live_or_404(db, Category, category_id, label="Category")


@router.get("", response_model=list[schemas.CategoryRuleRead])
def list_rules(db: Session = Depends(get_db)) -> list[CategoryRule]:
    return list(
        db.scalars(
            select(CategoryRule).order_by(
                CategoryRule.priority.desc(), CategoryRule.id
            )
        )
    )


@router.post(
    "", response_model=schemas.CategoryRuleRead, status_code=status.HTTP_201_CREATED
)
def create_rule(
    payload: schemas.CategoryRuleCreate, db: Session = Depends(get_db)
) -> CategoryRule:
    _category_or_404(db, payload.category_id)
    rule = CategoryRule(**payload.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.patch("/reorder", response_model=list[schemas.CategoryRuleRead])
def reorder_rules(
    payload: schemas.RuleReorderRequest, db: Session = Depends(get_db)
) -> list[CategoryRule]:
    rules = {
        r.id: r
        for r in db.scalars(
            select(CategoryRule).where(CategoryRule.id.in_(payload.rule_ids))
        )
    }
    missing = [rid for rid in payload.rule_ids if rid not in rules]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown rule id(s): {missing}.",
        )
    # First in the list = highest priority.
    total = len(payload.rule_ids)
    for index, rid in enumerate(payload.rule_ids):
        rules[rid].priority = total - index
    db.commit()
    return [rules[rid] for rid in payload.rule_ids]


@router.delete("/{rule_id}", response_model=schemas.DeletedResponse)
def delete_rule(
    rule_id: int, db: Session = Depends(get_db)
) -> schemas.DeletedResponse:
    rule = get_live_or_404(db, CategoryRule, rule_id, label="Rule")
    db.delete(rule)
    db.commit()
    return schemas.DeletedResponse(id=rule_id, deleted=True)


@router.post("/apply", response_model=schemas.RuleApplyResponse)
def apply_rules(
    month: str | None = None, db: Session = Depends(get_db)
) -> schemas.RuleApplyResponse:
    rules = sort_rules(
        [
            Rule(
                match_field=r.match_field.value,
                pattern=r.pattern,
                category_id=r.category_id,
                priority=r.priority,
            )
            for r in db.scalars(select(CategoryRule))
        ]
    )
    if not rules:
        return schemas.RuleApplyResponse(changed=0)

    stmt = select(Transaction).where(Transaction.category_id.is_(None))
    if month is not None:
        validate_month(month)
        stmt = stmt.where(func.strftime("%Y-%m", Transaction.date) == month)

    changed = 0
    for txn in db.scalars(stmt):
        proposed = propose_category(rules, txn.payee, txn.memo)
        if proposed is not None:
            txn.category_id = proposed
            changed += 1
    db.commit()
    return schemas.RuleApplyResponse(changed=changed)
