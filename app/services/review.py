from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import case, select
from sqlalchemy.orm import Session, selectinload

from app.db.enums import AnchorType, ProgressStatus, ResourceType
from app.db.models import Anchor, ProgressRecord

REVIEW_QUEUE_STATUSES: tuple[ProgressStatus, ProgressStatus] = (
    ProgressStatus.HARD,
    ProgressStatus.REVIEW,
)


@dataclass(slots=True)
class ReviewQueueItem:
    queue_key: str
    dom_id: str
    status: ProgressStatus
    status_label: str
    course_id: int
    course_title: str
    module_id: int
    module_title: str
    resource_id: int
    resource_title: str
    resource_type: ResourceType
    unit_kind: str
    unit_kind_label: str
    unit_title: str
    source_page: int
    source_anchor: str | None
    source_label: str
    last_interacted_at: datetime | None
    last_interacted_label: str | None
    can_open_source: bool


def list_review_queue(db: Session) -> list[ReviewQueueItem]:
    status_order = case(
        (ProgressRecord.status == ProgressStatus.HARD, 0),
        (ProgressRecord.status == ProgressStatus.REVIEW, 1),
        else_=2,
    )
    statement = (
        select(ProgressRecord)
        .where(
            ProgressRecord.status.in_(REVIEW_QUEUE_STATUSES),
            ProgressRecord.resource_id.is_not(None),
        )
        .options(
            selectinload(ProgressRecord.course),
            selectinload(ProgressRecord.module),
            selectinload(ProgressRecord.resource),
            selectinload(ProgressRecord.outline_item),
            selectinload(ProgressRecord.anchor).selectinload(Anchor.outline_item),
        )
        .order_by(
            status_order,
            ProgressRecord.last_interacted_at.desc(),
            ProgressRecord.id.desc(),
        )
    )

    seen_keys: set[tuple[str, int]] = set()
    queue_items: list[ReviewQueueItem] = []
    for record in db.scalars(statement):
        queue_key = _resolve_queue_key(record)
        if queue_key is None or queue_key in seen_keys:
            continue

        queue_item = _build_review_queue_item(record, queue_key=queue_key)
        if queue_item is None:
            continue

        seen_keys.add(queue_key)
        queue_items.append(queue_item)

    return queue_items


def filter_review_queue(
    queue_items: list[ReviewQueueItem],
    *,
    course_id: int | None = None,
    module_id: int | None = None,
    resource_id: int | None = None,
) -> list[ReviewQueueItem]:
    filtered_items = queue_items
    if course_id is not None:
        filtered_items = [item for item in filtered_items if item.course_id == course_id]
    if module_id is not None:
        filtered_items = [item for item in filtered_items if item.module_id == module_id]
    if resource_id is not None:
        filtered_items = [item for item in filtered_items if item.resource_id == resource_id]
    return filtered_items


def build_review_stats(queue_items: list[ReviewQueueItem]) -> dict[str, int]:
    return {
        "total": len(queue_items),
        "hard": sum(1 for item in queue_items if item.status == ProgressStatus.HARD),
        "review": sum(1 for item in queue_items if item.status == ProgressStatus.REVIEW),
    }


def _resolve_queue_key(record: ProgressRecord) -> tuple[str, int] | None:
    if record.outline_item_id is not None:
        return ("outline-item", record.outline_item_id)
    if record.anchor_id is not None:
        return ("anchor", record.anchor_id)
    if record.resource_id is not None:
        return ("resource", record.resource_id)
    return None


def _build_review_queue_item(
    record: ProgressRecord,
    *,
    queue_key: tuple[str, int],
) -> ReviewQueueItem | None:
    if record.course is None or record.module is None or record.resource is None:
        return None

    unit_kind = queue_key[0]
    unit_title = record.resource.title
    unit_kind_label = "Resource"
    source_page = 1
    source_anchor: str | None = None
    source_label = "Start of resource"

    if record.outline_item is not None:
        unit_kind = "outline-item"
        unit_title = record.outline_item.title
        unit_kind_label = "Outline item"
        source_page = record.outline_item.page_number or 1
        source_anchor = (
            "pdf-reader"
            if record.outline_item.page_number is not None
            else f"outline-item-{record.outline_item.id}"
        )
        source_label = (
            f"Page {record.outline_item.page_number}"
            if record.outline_item.page_number is not None
            else "Outline without page target"
        )
    elif record.anchor is not None:
        if record.anchor.anchor_type == AnchorType.PDF_PAGE and record.anchor.page_number is not None:
            unit_kind = "page"
            unit_title = f"Page {record.anchor.page_number}"
            unit_kind_label = "Page"
            source_page = record.anchor.page_number
            source_anchor = "pdf-reader"
            source_label = f"Page {record.anchor.page_number}"
        elif record.anchor.anchor_type == AnchorType.OUTLINE_ITEM and record.anchor.outline_item_id is not None:
            unit_kind = "outline-item"
            unit_kind_label = "Outline item"
            unit_title = record.anchor.outline_item.title if record.anchor.outline_item is not None else record.resource.title
            source_page = record.anchor.page_number or 1
            source_anchor = (
                "pdf-reader"
                if record.anchor.page_number is not None
                else f"outline-item-{record.anchor.outline_item_id}"
            )
            source_label = (
                f"Page {record.anchor.page_number}"
                if record.anchor.page_number is not None
                else "Outline without page target"
            )

    can_open_source = record.resource.resource_type == ResourceType.PDF
    if can_open_source and source_anchor is None:
        source_anchor = "pdf-reader"

    queue_key_value = f"{unit_kind}-{queue_key[1]}"
    return ReviewQueueItem(
        queue_key=queue_key_value,
        dom_id=f"review-item-{queue_key_value}",
        status=record.status,
        status_label=_status_label(record.status),
        course_id=record.course.id,
        course_title=record.course.title,
        module_id=record.module.id,
        module_title=record.module.title,
        resource_id=record.resource.id,
        resource_title=record.resource.title,
        resource_type=record.resource.resource_type,
        unit_kind=unit_kind,
        unit_kind_label=unit_kind_label,
        unit_title=unit_title,
        source_page=source_page,
        source_anchor=source_anchor,
        source_label=source_label,
        last_interacted_at=record.last_interacted_at,
        last_interacted_label=_format_last_interacted(record.last_interacted_at),
        can_open_source=can_open_source,
    )


def _format_last_interacted(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.strftime("%Y-%m-%d %H:%M")


def _status_label(status: ProgressStatus) -> str:
    return status.value.replace("_", " ").title()
