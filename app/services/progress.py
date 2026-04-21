from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import AnchorType, ProgressStatus, ResourceType
from app.db.models import Anchor, Course, ProgressRecord, Resource, ResourceOutlineItem

STATUS_PROGRESS_POINTS: dict[ProgressStatus, int] = {
    ProgressStatus.NOT_STARTED: 0,
    ProgressStatus.IN_PROGRESS: 50,
    ProgressStatus.DONE: 100,
    ProgressStatus.REVIEW: 75,
    ProgressStatus.HARD: 25,
}

PROGRESS_STATUS_OPTIONS: list[dict[str, str]] = [
    {
        "value": status.value,
        "label": status.value.replace("_", " ").title(),
    }
    for status in ProgressStatus
]


def build_course_progress_context(courses: Sequence[Course], db: Session) -> dict[str, dict[int, dict[str, Any]]]:
    resources = [
        resource
        for course in courses
        for module in course.modules
        for resource in module.resources
    ]
    resource_views = build_resource_progress_views(resources, db)

    module_summaries: dict[int, dict[str, Any]] = {}
    for course in courses:
        for module in course.modules:
            module_summaries[module.id] = combine_progress_summaries(
                resource_views[resource.id]["summary"] for resource in module.resources
            )

    course_summaries: dict[int, dict[str, Any]] = {}
    for course in courses:
        course_summaries[course.id] = combine_progress_summaries(
            module_summaries[module.id] for module in course.modules
        )

    return {
        "courses": course_summaries,
        "modules": module_summaries,
        "resources": resource_views,
    }


def build_resource_progress_views(resources: Sequence[Resource], db: Session) -> dict[int, dict[str, Any]]:
    resource_list = [resource for resource in resources]
    resource_ids = [resource.id for resource in resource_list]
    outline_progress_by_item_id = _load_outline_progress_records(
        db,
        item_ids=[
            item.id
            for resource in resource_list
            for item in resource.outline_items
        ],
    )
    page_progress_by_key = _load_page_progress_records(db, resource_ids=resource_ids)

    resource_views: dict[int, dict[str, Any]] = {}
    for resource in resource_list:
        outline_statuses: dict[int, dict[str, Any]] = {}
        page_statuses: dict[int, dict[str, Any]] = {}

        if resource.outline_items:
            units: list[dict[str, Any]] = []
            for item in sorted(resource.outline_items, key=lambda value: (value.position, value.id)):
                record = outline_progress_by_item_id.get(item.id)
                status = record.status if record is not None else item.status
                unit_view = _build_unit_view(
                    status=status,
                    progress_percent=record.progress_percent if record is not None else None,
                    title=item.title,
                    page_number=item.page_number,
                    outline_item_id=item.id,
                    kind="outline_item",
                )
                units.append(unit_view)
                outline_statuses[item.id] = unit_view
        else:
            units = []
            for page_number in range(1, (resource.page_count or 0) + 1):
                progress_row = page_progress_by_key.get((resource.id, page_number))
                unit_view = _build_unit_view(
                    status=progress_row["status"] if progress_row is not None else ProgressStatus.NOT_STARTED,
                    progress_percent=progress_row["progress_percent"] if progress_row is not None else None,
                    title=f"Page {page_number}",
                    page_number=page_number,
                    kind="page",
                )
                units.append(unit_view)
                page_statuses[page_number] = unit_view

        resource_views[resource.id] = {
            "mode": "outline_item" if resource.outline_items else "page",
            "summary": build_progress_summary(units),
            "units": units,
            "outline_statuses": outline_statuses,
            "page_statuses": page_statuses,
        }

    return resource_views


def build_progress_summary(units: Sequence[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(unit["status"].value for unit in units)
    total_units = len(units)
    progress_points = sum(int(unit["progress_percent"]) for unit in units)
    return _build_summary_from_counts(
        counts=counts,
        total_units=total_units,
        progress_points=progress_points,
    )


def combine_progress_summaries(summaries: Iterable[dict[str, Any]]) -> dict[str, Any]:
    combined_counts: Counter[str] = Counter()
    total_units = 0
    progress_points = 0

    for summary in summaries:
        total_units += int(summary["total_units"])
        progress_points += int(summary["progress_points"])
        combined_counts.update(summary["counts"])

    return _build_summary_from_counts(
        counts=combined_counts,
        total_units=total_units,
        progress_points=progress_points,
    )


def build_default_page_status(page_number: int) -> dict[str, Any]:
    return _build_unit_view(
        status=ProgressStatus.NOT_STARTED,
        progress_percent=None,
        title=f"Page {page_number}",
        page_number=page_number,
        kind="page",
    )


def set_outline_item_status(
    db: Session,
    *,
    resource: Resource,
    outline_item_id: int,
    status: ProgressStatus,
) -> ResourceOutlineItem:
    outline_item = db.scalar(
        select(ResourceOutlineItem).where(
            ResourceOutlineItem.id == outline_item_id,
            ResourceOutlineItem.resource_id == resource.id,
        )
    )
    if outline_item is None:
        raise LookupError("Outline item not found.")

    outline_item.status = status
    _upsert_progress_record(
        db,
        filters=(ProgressRecord.outline_item_id == outline_item.id,),
        values={
            "course_id": resource.course_id,
            "module_id": resource.module_id,
            "resource_id": resource.id,
            "outline_item_id": outline_item.id,
        },
        status=status,
    )
    db.commit()
    db.refresh(outline_item)
    return outline_item


def set_page_status(
    db: Session,
    *,
    resource: Resource,
    page_number: int,
    status: ProgressStatus,
) -> Anchor | None:
    if resource.resource_type != ResourceType.PDF:
        raise ValueError("Page-level status is only supported for PDF resources.")
    if page_number < 1:
        raise ValueError("Page number must be positive.")
    if resource.page_count is not None and resource.page_count > 0 and page_number > resource.page_count:
        raise ValueError("Page number is outside the resource page range.")

    anchor = db.scalar(
        select(Anchor).where(
            Anchor.resource_id == resource.id,
            Anchor.anchor_type == AnchorType.PDF_PAGE,
            Anchor.page_number == page_number,
        )
    )

    if anchor is None and status == ProgressStatus.NOT_STARTED:
        return None

    if anchor is None:
        anchor = Anchor(
            resource_id=resource.id,
            anchor_type=AnchorType.PDF_PAGE,
            page_number=page_number,
        )
        db.add(anchor)
        db.flush()

    _upsert_progress_record(
        db,
        filters=(ProgressRecord.anchor_id == anchor.id,),
        values={
            "course_id": resource.course_id,
            "module_id": resource.module_id,
            "resource_id": resource.id,
            "anchor_id": anchor.id,
        },
        status=status,
    )
    db.commit()
    if anchor is not None:
        db.refresh(anchor)
    return anchor


def parse_progress_status(value: str) -> ProgressStatus:
    try:
        return ProgressStatus(value)
    except ValueError as exc:
        raise ValueError("Unknown progress status.") from exc


def _build_unit_view(
    *,
    status: ProgressStatus,
    progress_percent: int | None,
    title: str,
    kind: str,
    page_number: int | None = None,
    outline_item_id: int | None = None,
) -> dict[str, Any]:
    resolved_progress_percent = progress_percent
    if resolved_progress_percent is None:
        resolved_progress_percent = STATUS_PROGRESS_POINTS[status]

    return {
        "kind": kind,
        "title": title,
        "status": status,
        "status_label": status.value.replace("_", " ").title(),
        "progress_percent": resolved_progress_percent,
        "page_number": page_number,
        "outline_item_id": outline_item_id,
    }


def _build_summary_from_counts(
    *,
    counts: Counter[str],
    total_units: int,
    progress_points: int,
) -> dict[str, Any]:
    normalized_counts = {
        status.value: int(counts.get(status.value, 0))
        for status in ProgressStatus
    }
    aggregate_status = _resolve_aggregate_status(normalized_counts, total_units)
    progress_percent = 0
    if total_units > 0:
        progress_percent = int((progress_points / total_units) + 0.5)

    return {
        "status": aggregate_status,
        "status_label": aggregate_status.value.replace("_", " ").title(),
        "progress_percent": progress_percent,
        "total_units": total_units,
        "started_units": total_units - normalized_counts[ProgressStatus.NOT_STARTED.value],
        "done_units": normalized_counts[ProgressStatus.DONE.value],
        "review_units": normalized_counts[ProgressStatus.REVIEW.value],
        "hard_units": normalized_counts[ProgressStatus.HARD.value],
        "counts": normalized_counts,
        "progress_points": progress_points,
        "is_empty": total_units == 0,
    }


def _resolve_aggregate_status(counts: dict[str, int], total_units: int) -> ProgressStatus:
    if total_units == 0:
        return ProgressStatus.NOT_STARTED
    if counts[ProgressStatus.DONE.value] == total_units:
        return ProgressStatus.DONE
    if counts[ProgressStatus.HARD.value] > 0:
        return ProgressStatus.HARD
    if counts[ProgressStatus.REVIEW.value] > 0:
        return ProgressStatus.REVIEW
    if counts[ProgressStatus.IN_PROGRESS.value] > 0:
        return ProgressStatus.IN_PROGRESS
    if counts[ProgressStatus.DONE.value] > 0:
        return ProgressStatus.IN_PROGRESS
    return ProgressStatus.NOT_STARTED


def _load_outline_progress_records(
    db: Session,
    *,
    item_ids: Sequence[int],
) -> dict[int, ProgressRecord]:
    if not item_ids:
        return {}

    records = db.scalars(
        select(ProgressRecord)
        .where(ProgressRecord.outline_item_id.in_(item_ids))
        .order_by(ProgressRecord.id.desc())
    ).all()

    progress_by_item_id: dict[int, ProgressRecord] = {}
    for record in records:
        if record.outline_item_id is None or record.outline_item_id in progress_by_item_id:
            continue
        progress_by_item_id[record.outline_item_id] = record
    return progress_by_item_id


def _load_page_progress_records(
    db: Session,
    *,
    resource_ids: Sequence[int],
) -> dict[tuple[int, int], dict[str, Any]]:
    if not resource_ids:
        return {}

    rows = db.execute(
        select(
            Anchor.resource_id,
            Anchor.page_number,
            ProgressRecord.status,
            ProgressRecord.progress_percent,
            ProgressRecord.id,
        )
        .join(ProgressRecord, ProgressRecord.anchor_id == Anchor.id)
        .where(
            Anchor.resource_id.in_(resource_ids),
            Anchor.anchor_type == AnchorType.PDF_PAGE,
            Anchor.page_number.is_not(None),
        )
        .order_by(ProgressRecord.id.desc())
    ).all()

    progress_by_page: dict[tuple[int, int], dict[str, Any]] = {}
    for row in rows:
        key = (int(row.resource_id), int(row.page_number))
        if key in progress_by_page:
            continue
        progress_by_page[key] = {
            "status": row.status,
            "progress_percent": row.progress_percent,
        }
    return progress_by_page


def _upsert_progress_record(
    db: Session,
    *,
    filters: Sequence[Any],
    values: dict[str, Any],
    status: ProgressStatus,
) -> None:
    record = db.scalar(select(ProgressRecord).where(*filters).order_by(ProgressRecord.id.desc()))
    if status == ProgressStatus.NOT_STARTED:
        if record is not None:
            db.delete(record)
        return

    if record is None:
        record = ProgressRecord(
            **values,
            status=status,
            progress_percent=STATUS_PROGRESS_POINTS[status],
            last_interacted_at=datetime.now(timezone.utc),
        )
        db.add(record)
        return

    for key, value in values.items():
        setattr(record, key, value)
    record.status = status
    record.progress_percent = STATUS_PROGRESS_POINTS[status]
    record.last_interacted_at = datetime.now(timezone.utc)
