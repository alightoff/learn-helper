from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.courses import create_course, list_courses
from app.services.progress import build_course_progress_context
from app.web import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse, name="dashboard_home")
@router.get("/courses", response_class=HTMLResponse, name="courses_index")
async def dashboard_home(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    courses = list_courses(db)
    progress_context = build_course_progress_context(courses, db)
    course_summaries = progress_context["courses"]
    stats = {
        "course_count": len(courses),
        "module_count": sum(len(course.modules) for course in courses),
        "pdf_count": sum(len(course.resources) for course in courses),
        "study_unit_count": sum(summary["total_units"] for summary in course_summaries.values()),
    }
    return templates.TemplateResponse(
        request,
        "pages/dashboard.html",
        {
            "page_title": "Courses",
            "courses": courses,
            "stats": stats,
            "notice": request.query_params.get("notice"),
            "error": request.query_params.get("error"),
            "course_progress_summaries": course_summaries,
        },
    )


@router.post("/courses", name="create_course_action")
async def create_course_action(
    request: Request,
    title: str = Form(...),
    description: str | None = Form(default=None),
    topic: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        course = create_course(
            db,
            title=title,
            description=description,
            topic=topic,
        )
    except ValueError as exc:
        url = str(request.url_for("courses_index"))
        return RedirectResponse(
            f"{url}?{urlencode({'error': str(exc)})}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    return RedirectResponse(
        url=str(request.url_for("course_detail", course_id=course.id)),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/health", name="health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
