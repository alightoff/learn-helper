from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.review import build_review_stats, filter_review_queue, list_review_queue
from app.web import templates

router = APIRouter()


@router.get("/review", response_class=HTMLResponse, name="review_index")
async def review_index(
    request: Request,
    course_id_value: str | None = Query(default=None, alias="course_id"),
    module_id_value: str | None = Query(default=None, alias="module_id"),
    resource_id_value: str | None = Query(default=None, alias="resource_id"),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    course_id = _parse_optional_int_query(course_id_value, field_name="course_id")
    module_id = _parse_optional_int_query(module_id_value, field_name="module_id")
    resource_id = _parse_optional_int_query(resource_id_value, field_name="resource_id")

    all_queue_items = list_review_queue(db)
    filtered_queue_items = filter_review_queue(
        all_queue_items,
        course_id=course_id,
        module_id=module_id,
        resource_id=resource_id,
    )

    course_options_map: dict[int, dict[str, int | str]] = {}
    module_options_map: dict[int, dict[str, int | str]] = {}
    resource_options_map: dict[int, dict[str, int | str]] = {}
    for item in all_queue_items:
        course_options_map[item.course_id] = {
            "id": item.course_id,
            "label": item.course_title,
        }
        module_options_map[item.module_id] = {
            "id": item.module_id,
            "course_id": item.course_id,
            "label": f"{item.course_title} / {item.module_title}",
        }
        resource_options_map[item.resource_id] = {
            "id": item.resource_id,
            "course_id": item.course_id,
            "module_id": item.module_id,
            "label": f"{item.module_title} / {item.resource_title}",
        }

    course_options = sorted(course_options_map.values(), key=lambda option: str(option["label"]).lower())
    module_options = sorted(module_options_map.values(), key=lambda option: str(option["label"]).lower())
    resource_options = sorted(resource_options_map.values(), key=lambda option: str(option["label"]).lower())

    return templates.TemplateResponse(
        request,
        "pages/review.html",
        {
            "page_title": "Review",
            "review_queue": filtered_queue_items,
            "queue_stats": build_review_stats(filtered_queue_items),
            "total_queue_stats": build_review_stats(all_queue_items),
            "selected_filters": {
                "course_id": course_id,
                "module_id": module_id,
                "resource_id": resource_id,
            },
            "course_options": course_options,
            "module_options": module_options,
            "resource_options": resource_options,
        },
    )


def _parse_optional_int_query(value: str | None, *, field_name: str) -> int | None:
    if value is None:
        return None

    normalized = value.strip()
    if not normalized:
        return None

    try:
        parsed_value = int(normalized)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_name} must be a valid integer.",
        ) from exc

    if parsed_value < 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_name} must be greater than 0.",
        )
    return parsed_value
