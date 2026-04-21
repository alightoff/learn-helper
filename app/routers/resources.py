from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.db.enums import ResourceType
from app.db.session import get_db
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

    page_count = resource.page_count or 0
    initial_page = _clamp_page(page, page_count)

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
        },
    )


def _clamp_page(requested_page: int, page_count: int) -> int:
    if page_count < 1:
        return max(requested_page, 1)
    return max(1, min(requested_page, page_count))
