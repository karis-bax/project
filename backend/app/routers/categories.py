"""Category and category-group routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .. import schemas
from ..deps import get_db
from ..models import Category, CategoryGroup, Transaction

router = APIRouter(prefix="/api", tags=["categories"])


def _group_or_404(db: Session, group_id: int) -> CategoryGroup:
    group = db.get(CategoryGroup, group_id)
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Category group {group_id} not found.",
        )
    return group


def _category_or_404(db: Session, category_id: int) -> Category:
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Category {category_id} not found.",
        )
    return category


@router.get("/categories", response_model=list[schemas.CategoryGroupWithCategories])
def list_categories_nested(
    include_archived: bool = False, db: Session = Depends(get_db)
) -> list[schemas.CategoryGroupWithCategories]:
    groups = list(
        db.scalars(
            select(CategoryGroup).order_by(CategoryGroup.sort_order, CategoryGroup.id)
        )
    )
    cat_stmt = select(Category).order_by(Category.sort_order, Category.id)
    if not include_archived:
        cat_stmt = cat_stmt.where(Category.archived.is_(False))
    categories = list(db.scalars(cat_stmt))

    by_group: dict[int, list[Category]] = {}
    for cat in categories:
        by_group.setdefault(cat.group_id, []).append(cat)

    return [
        schemas.CategoryGroupWithCategories(
            id=group.id,
            name=group.name,
            sort_order=group.sort_order,
            created_at=group.created_at,
            updated_at=group.updated_at,
            categories=[
                schemas.CategoryRead.model_validate(cat)
                for cat in by_group.get(group.id, [])
            ],
        )
        for group in groups
    ]


@router.post(
    "/categories",
    response_model=schemas.CategoryRead,
    status_code=status.HTTP_201_CREATED,
)
def create_category(
    payload: schemas.CategoryCreate, db: Session = Depends(get_db)
) -> Category:
    _group_or_404(db, payload.group_id)
    category = Category(**payload.model_dump())
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


@router.patch("/categories/{category_id}", response_model=schemas.CategoryRead)
def update_category(
    category_id: int,
    payload: schemas.CategoryCreate | schemas.CategoryBase,
    db: Session = Depends(get_db),
) -> Category:
    category = _category_or_404(db, category_id)
    data = payload.model_dump(exclude_unset=True)
    if "group_id" in data:
        _group_or_404(db, data["group_id"])
    for field, value in data.items():
        setattr(category, field, value)
    db.commit()
    db.refresh(category)
    return category


@router.delete("/categories/{category_id}", response_model=schemas.CategoryRead)
def delete_category(
    category_id: int,
    reassign_to: int | None = None,
    db: Session = Depends(get_db),
) -> Category:
    category = _category_or_404(db, category_id)
    txn_count = db.scalar(
        select(func.count())
        .select_from(Transaction)
        .where(Transaction.category_id == category_id)
    )

    if txn_count and reassign_to is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Category '{category.name}' has {txn_count} transaction(s). "
                f"Pass ?reassign_to=<category_id> to move them before deleting."
            ),
        )

    if reassign_to is not None:
        if reassign_to == category_id:
            raise HTTPException(
                status_code=422,
                detail="reassign_to must differ from the category being deleted.",
            )
        _category_or_404(db, reassign_to)
        db.execute(
            update(Transaction)
            .where(Transaction.category_id == category_id)
            .values(category_id=reassign_to)
        )

    # Soft delete: archive rather than hard delete so history is preserved.
    category.archived = True
    db.commit()
    db.refresh(category)
    return category


@router.post(
    "/category-groups",
    response_model=schemas.CategoryGroupRead,
    status_code=status.HTTP_201_CREATED,
)
def create_category_group(
    payload: schemas.CategoryGroupCreate, db: Session = Depends(get_db)
) -> CategoryGroup:
    group = CategoryGroup(**payload.model_dump())
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


@router.patch(
    "/category-groups/reorder", response_model=list[schemas.CategoryGroupRead]
)
def reorder_category_groups(
    payload: schemas.GroupReorderRequest, db: Session = Depends(get_db)
) -> list[CategoryGroup]:
    groups = {
        group.id: group
        for group in db.scalars(
            select(CategoryGroup).where(CategoryGroup.id.in_(payload.group_ids))
        )
    }
    missing = [gid for gid in payload.group_ids if gid not in groups]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown category group id(s): {missing}.",
        )
    for order, gid in enumerate(payload.group_ids):
        groups[gid].sort_order = order
    db.commit()
    return [groups[gid] for gid in payload.group_ids]
