from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.courses import create_course, list_courses
from app.services.progress import build_course_progress_context
from app.services.review import build_review_stats, list_review_queue
from app.services.sessions import build_sessions_page_context
from app.web import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse, name="dashboard_home")
async def dashboard_home(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    context = _build_learning_overview_context(request, db)
    return templates.TemplateResponse(
        request,
        "pages/dashboard.html",
        {
            "page_title": "Dashboard",
            **context,
        },
    )


@router.get("/courses", response_class=HTMLResponse, name="courses_index")
async def courses_index(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    context = _build_learning_overview_context(request, db)
    return templates.TemplateResponse(
        request,
        "pages/courses.html",
        {
            "page_title": "Courses",
            **context,
        },
    )


@router.get("/reader", response_class=HTMLResponse, name="reader_index")
async def reader_index(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    context = _build_learning_overview_context(request, db)
    return templates.TemplateResponse(
        request,
        "pages/reader.html",
        {
            "page_title": "PDF Reader",
            **context,
        },
    )


def _build_learning_overview_context(request: Request, db: Session) -> dict[str, object]:
    courses = list_courses(db)
    progress_context = build_course_progress_context(courses, db)
    course_summaries = progress_context["courses"]
    module_summaries = progress_context["modules"]
    review_queue = list_review_queue(db)
    review_stats = build_review_stats(review_queue)
    sessions_context = build_sessions_page_context(db)
    weekly_study_seconds = sum(int(row["total_seconds"]) for row in sessions_context["daily_stats"])
    recent_resources = [
        {
            "resource": resource,
            "course": course,
            "module": module,
            "progress": progress_context["resources"][resource.id]["summary"],
            "viewer_url": request.url_for("resource_detail", resource_id=resource.id),
        }
        for course in courses
        for module in course.modules
        for resource in module.resources
    ]
    recent_resources.sort(
        key=lambda item: (
            item["resource"].created_at is None,
            item["resource"].created_at,
            item["resource"].id,
        ),
        reverse=True,
    )
    stats = {
        "course_count": len(courses),
        "active_course_count": sum(
            1
            for summary in course_summaries.values()
            if summary["status"].value != "done"
        ),
        "module_count": sum(len(course.modules) for course in courses),
        "modules_done_count": sum(
            1
            for summary in module_summaries.values()
            if summary["total_units"] > 0 and summary["status"].value == "done"
        ),
        "pdf_count": sum(len(course.resources) for course in courses),
        "study_unit_count": sum(summary["total_units"] for summary in course_summaries.values()),
        "review_queue_count": review_stats["total"],
        "weekly_study_time": _format_dashboard_hours(weekly_study_seconds),
    }
    return {
        "courses": courses,
        "stats": stats,
        "notice": request.query_params.get("notice"),
        "error": request.query_params.get("error"),
        "course_progress_summaries": course_summaries,
        "review_queue": review_queue[:6],
        "review_stats": review_stats,
        "active_session": sessions_context["active_session"],
        "daily_stats": sessions_context["daily_stats"],
        "top_resources": recent_resources[:5],
        "resources": recent_resources,
    }


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


def _format_dashboard_hours(seconds: int) -> str:
    if seconds <= 0:
        return "0h"
    hours = seconds / 3600
    if hours < 10:
        return f"{hours:.1f}h"
    return f"{hours:.0f}h"
