from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.models import Course
from app.db.session import get_db
from app.services.courses import create_course, get_course_detail
from app.services.modules import create_module, get_module_with_course
from app.services.resources import PdfImportError, build_outline_tree, import_pdf_resource
from app.web import templates

router = APIRouter()


@router.get("/courses/{course_id}", response_class=HTMLResponse, name="course_detail")
async def course_detail(
    request: Request,
    course_id: int,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    course = get_course_detail(db, course_id)
    if course is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found.")

    module_views = []
    for module in sorted(course.modules, key=lambda item: (item.position, item.id)):
        resource_views = []
        for resource in sorted(
            module.resources,
            key=lambda item: (item.created_at is None, item.created_at, item.id),
            reverse=True,
        ):
            resource_views.append(
                {
                    "resource": resource,
                    "outline_tree": build_outline_tree(resource.outline_items),
                    "outline_count": len(resource.outline_items),
                    "file_url": request.url_for("uploads", path=resource.file_path),
                    "viewer_url": request.url_for("resource_detail", resource_id=resource.id),
                }
            )

        module_views.append(
            {
                "module": module,
                "resources": resource_views,
            }
        )

    return templates.TemplateResponse(
        request,
        "pages/course_detail.html",
        {
            "page_title": course.title,
            "course": course,
            "module_views": module_views,
            "notice": request.query_params.get("notice"),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/courses/{course_id}/modules", name="create_module_action")
async def create_module_action(
    request: Request,
    course_id: int,
    title: str = Form(...),
    description: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    course = db.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found.")

    try:
        create_module(db, course=course, title=title, description=description)
    except ValueError as exc:
        return _redirect_to_course(request, course.id, error=str(exc))

    return _redirect_to_course(request, course.id, notice="Module added.")


@router.post("/modules/{module_id}/resources/pdf", name="upload_pdf_action")
async def upload_pdf_action(
    request: Request,
    module_id: int,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    description: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    module = get_module_with_course(db, module_id)
    if module is None or module.course is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Module not found.")

    try:
        import_pdf_resource(
            db,
            settings=request.app.state.settings,
            course=module.course,
            module=module,
            upload=file,
            title=title,
            description=description,
        )
    except PdfImportError as exc:
        await file.close()
        return _redirect_to_course(request, module.course.id, error=str(exc), anchor=f"module-{module.id}")
    finally:
        await file.close()

    return _redirect_to_course(
        request,
        module.course.id,
        notice="PDF imported.",
        anchor=f"module-{module.id}",
    )

def _redirect_to_course(
    request: Request,
    course_id: int,
    *,
    notice: str | None = None,
    error: str | None = None,
    anchor: str | None = None,
) -> RedirectResponse:
    url = str(request.url_for("course_detail", course_id=course_id))
    query = {key: value for key, value in {"notice": notice, "error": error}.items() if value}
    if query:
        url = f"{url}?{urlencode(query)}"
    if anchor:
        url = f"{url}#{anchor}"
    return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)
