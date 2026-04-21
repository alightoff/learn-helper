from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Course, Module


def get_module_with_course(db: Session, module_id: int) -> Module | None:
    statement = (
        select(Module)
        .where(Module.id == module_id)
        .options(selectinload(Module.course))
    )
    return db.scalar(statement)


def create_module(
    db: Session,
    *,
    course: Course,
    title: str,
    description: str | None = None,
) -> Module:
    normalized_title = title.strip()
    if not normalized_title:
        raise ValueError("Module title is required.")

    next_position = db.scalar(
        select(func.coalesce(func.max(Module.position) + 1, 0)).where(Module.course_id == course.id)
    )

    module = Module(
        course_id=course.id,
        title=normalized_title,
        description=_clean_optional_text(description),
        position=int(next_position or 0),
    )
    db.add(module)
    db.commit()
    db.refresh(module)
    return module


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = value.strip()
    return normalized or None
