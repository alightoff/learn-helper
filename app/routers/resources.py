from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi import Form
from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db.enums import ResourceType
from app.db.session import get_db
from app.services.courses import get_course_detail
from app.services.progress import (
    PROGRESS_STATUS_OPTIONS,
    build_course_progress_context,
    build_default_page_status,
    parse_progress_status,
    set_outline_item_status,
    set_page_status,
)
from app.services.resources import build_outline_tree, get_resource_detail
from app.web import templates

router = APIRouter()


@router.get("/resources/{resource_id}", response_class=HTMLResponse, name="resource_detail")
async def resource_detail(
    request: Request,
    resource_id: int,
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    resource = get_resource_detail(db, resource_id)
    if resource is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found.")
    if resource.resource_type != ResourceType.PDF:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Only PDF resources are supported.")

    course = get_course_detail(db, resource.course_id)
    if course is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found.")

    page_count = resource.page_count or 0
    initial_page = _clamp_page(page, page_count)
    progress_context = build_course_progress_context([course], db)
    resource_progress = progress_context["resources"][resource.id]
    current_page_status = resource_progress["page_statuses"].get(initial_page, build_default_page_status(initial_page))

    return templates.TemplateResponse(
        request,
        "pages/resource_detail.html",
        {
            "page_title": resource.title,
            "shell_mode": "wide",
            "resource": resource,
            "outline_tree": build_outline_tree(resource.outline_items),
            "outline_count": len(resource.outline_items),
            "file_url": request.url_for("uploads", path=resource.file_path),
            "course_url": request.url_for("course_detail", course_id=resource.course_id),
            "initial_page": initial_page,
            "course_progress": progress_context["courses"][course.id],
            "module_progress": progress_context["modules"][resource.module_id],
            "resource_progress": resource_progress,
            "current_page_status": current_page_status,
            "progress_status_options": PROGRESS_STATUS_OPTIONS,
            "notice": request.query_params.get("notice"),
            "error": request.query_params.get("error"),
        },
    )


@router.post(
    "/resources/{resource_id}/outline-items/{outline_item_id}/status",
    name="update_outline_item_status_action",
)
async def update_outline_item_status_action(
    request: Request,
    resource_id: int,
    outline_item_id: int,
    status_value: str = Form(...),
    return_page: int = Form(default=1),
    redirect_anchor: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    resource = get_resource_detail(db, resource_id)
    if resource is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found.")

    try:
        set_outline_item_status(
            db,
            resource=resource,
            outline_item_id=outline_item_id,
            status=parse_progress_status(status_value),
        )
    except LookupError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outline item not found.") from None
    except ValueError as exc:
        return _redirect_to_resource(
            request,
            resource_id,
            page=return_page,
            error=str(exc),
            anchor=redirect_anchor,
        )

    return _redirect_to_resource(
        request,
        resource_id,
        page=return_page,
        notice="Outline item status updated.",
        anchor=redirect_anchor,
    )


@router.post("/resources/{resource_id}/pages/status", name="update_page_status_action")
async def update_page_status_action(
    request: Request,
    resource_id: int,
    page_number: int = Form(...),
    status_value: str = Form(...),
    redirect_anchor: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    resource = get_resource_detail(db, resource_id)
    if resource is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found.")

    try:
        set_page_status(
            db,
            resource=resource,
            page_number=page_number,
            status=parse_progress_status(status_value),
        )
    except ValueError as exc:
        return _redirect_to_resource(
            request,
            resource_id,
            page=page_number,
            error=str(exc),
            anchor=redirect_anchor,
        )

    return _redirect_to_resource(
        request,
        resource_id,
        page=page_number,
        notice="Page status updated.",
        anchor=redirect_anchor,
    )


def _clamp_page(requested_page: int, page_count: int) -> int:
    if page_count < 1:
        return max(requested_page, 1)
    return max(1, min(requested_page, page_count))


def _redirect_to_resource(
    request: Request,
    resource_id: int,
    *,
    page: int,
    notice: str | None = None,
    error: str | None = None,
    anchor: str | None = None,
) -> RedirectResponse:
    url = str(request.url_for("resource_detail", resource_id=resource_id))
    query = {"page": page}
    if notice:
        query["notice"] = notice
    if error:
        query["error"] = error
    url = f"{url}?{urlencode(query)}"
    if anchor:
        url = f"{url}#{anchor}"
    return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)
