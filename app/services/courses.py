from __future__ import annotations

import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Course, Module, Resource

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def list_courses(db: Session) -> list[Course]:
    statement = (
        select(Course)
        .options(selectinload(Course.modules), selectinload(Course.resources))
        .order_by(Course.created_at.desc(), Course.id.desc())
    )
    return list(db.scalars(statement))


def get_course_detail(db: Session, course_id: int) -> Course | None:
    statement = (
        select(Course)
        .where(Course.id == course_id)
        .options(
            selectinload(Course.modules)
            .selectinload(Module.resources)
            .selectinload(Resource.outline_items)
        )
    )
    return db.scalar(statement)


def create_course(
    db: Session,
    *,
    title: str,
    description: str | None = None,
    topic: str | None = None,
) -> Course:
    normalized_title = title.strip()
    if not normalized_title:
        raise ValueError("Course title is required.")

    course = Course(
        title=normalized_title,
        slug=_build_unique_slug(db, normalized_title),
        description=_clean_optional_text(description),
        topic=_clean_optional_text(topic),
    )
    db.add(course)
    db.commit()
    db.refresh(course)
    return course


def slugify(value: str, *, fallback: str = "course") -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = _SLUG_RE.sub("-", ascii_value).strip("-")
    return slug or fallback


def _build_unique_slug(db: Session, title: str) -> str:
    base_slug = slugify(title)
    candidate = base_slug
    suffix = 2

    while db.scalar(select(Course.id).where(Course.slug == candidate)) is not None:
        candidate = f"{base_slug}-{suffix}"
        suffix += 1

    return candidate


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = value.strip()
    return normalized or None
