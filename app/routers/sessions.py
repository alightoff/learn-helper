from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.progress import parse_progress_status
from app.services.sessions import (
    StudySessionError,
    build_sessions_page_context,
    complete_study_session_with_feedback,
    parse_optional_minutes,
    parse_optional_outline_item_id,
    parse_optional_page_number,
    parse_optional_resource_id,
    parse_optional_target_cycles,
    parse_session_type,
    parse_timer_mode,
    pause_study_session,
    resume_study_session,
    start_study_session,
    stop_study_session,
)
from app.web import templates

router = APIRouter()


@router.get("/sessions", response_class=HTMLResponse, name="sessions_index")
async def sessions_index(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    page_context = build_sessions_page_context(db)
    return templates.TemplateResponse(
        request,
        "pages/sessions.html",
        {
            "page_title": "Sessions",
            "notice": request.query_params.get("notice"),
            "error": request.query_params.get("error"),
            **page_context,
        },
    )


@router.post("/sessions/start", name="start_study_session_action")
async def start_study_session_action(
    request: Request,
    session_type_value: str = Form(...),
    timer_mode_value: str = Form(...),
    resource_id_value: str | None = Form(default=None),
    outline_item_id_value: str | None = Form(default=None),
    work_interval_minutes_value: str | None = Form(default=None),
    break_interval_minutes_value: str | None = Form(default=None),
    target_cycles_value: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        study_session = start_study_session(
            db,
            session_type=parse_session_type(session_type_value),
            timer_mode=parse_timer_mode(timer_mode_value),
            resource_id=parse_optional_resource_id(resource_id_value),
            outline_item_id=parse_optional_outline_item_id(outline_item_id_value),
            work_interval_minutes=parse_optional_minutes(
                work_interval_minutes_value,
                field_label="Pomodoro work interval",
            ),
            break_interval_minutes=parse_optional_minutes(
                break_interval_minutes_value,
                field_label="Pomodoro break interval",
            ),
            target_cycles=parse_optional_target_cycles(target_cycles_value),
        )
    except StudySessionError as exc:
        return _redirect_to_sessions(request, error=str(exc))

    return _redirect_after_start(
        request,
        db=db,
        resource_id=study_session.resource_id,
        outline_item_id=study_session.outline_item_id,
        notice="Study session started.",
    )


@router.post("/sessions/{session_id}/pause", name="pause_study_session_action")
async def pause_study_session_action(
    request: Request,
    session_id: int,
    return_to_value: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        pause_study_session(db, session_id=session_id)
    except StudySessionError as exc:
        return _redirect_to_target_or_sessions(request, return_to_value, error=str(exc))

    return _redirect_to_target_or_sessions(
        request,
        return_to_value,
        notice="Study session paused.",
    )


@router.post("/sessions/{session_id}/resume", name="resume_study_session_action")
async def resume_study_session_action(
    request: Request,
    session_id: int,
    return_to_value: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        resume_study_session(db, session_id=session_id)
    except StudySessionError as exc:
        return _redirect_to_target_or_sessions(request, return_to_value, error=str(exc))

    return _redirect_to_target_or_sessions(
        request,
        return_to_value,
        notice="Study session resumed.",
    )


@router.post("/sessions/{session_id}/stop", name="stop_study_session_action")
async def stop_study_session_action(
    request: Request,
    session_id: int,
    return_to_value: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        stop_study_session(db, session_id=session_id)
    except StudySessionError as exc:
        return _redirect_to_target_or_sessions(request, return_to_value, error=str(exc))

    return _redirect_to_target_or_sessions(
        request,
        return_to_value,
        notice="Study session saved.",
    )


@router.post("/sessions/{session_id}/complete", name="complete_study_session_action")
async def complete_study_session_action(
    request: Request,
    session_id: int,
    feedback_status_value: str | None = Form(default=None),
    page_number_value: str | None = Form(default=None),
    return_to_value: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        page_number = parse_optional_page_number(page_number_value)
        feedback_status = None
        if feedback_status_value and feedback_status_value.strip():
            feedback_status = parse_progress_status(feedback_status_value)
        complete_study_session_with_feedback(
            db,
            session_id=session_id,
            feedback_status=feedback_status,
            page_number=page_number,
        )
    except (StudySessionError, ValueError) as exc:
        return _redirect_to_target_or_sessions(request, return_to_value, error=str(exc))

    return _redirect_to_target_or_sessions(
        request,
        return_to_value,
        notice="Study session completed.",
    )


def _redirect_after_start(
    request: Request,
    *,
    db: Session,
    resource_id: int | None,
    outline_item_id: int | None,
    notice: str,
) -> RedirectResponse:
    if resource_id is None:
        return _redirect_to_sessions(request, notice=notice)

    page_number = 1
    if outline_item_id is not None:
        from app.db.models import ResourceOutlineItem

        outline_item = db.get(ResourceOutlineItem, outline_item_id)
        if outline_item is not None and outline_item.page_number is not None:
            page_number = outline_item.page_number

    resource_url = str(request.url_for("resource_detail", resource_id=resource_id))
    redirect_target = _append_query_params(resource_url, {"page": page_number, "notice": notice})
    return RedirectResponse(url=f"{redirect_target}#pdf-reader", status_code=status.HTTP_303_SEE_OTHER)


def _redirect_to_sessions(
    request: Request,
    *,
    notice: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    url = str(request.url_for("sessions_index"))
    query = {key: value for key, value in {"notice": notice, "error": error}.items() if value}
    if query:
        url = _append_query_params(url, query)
    return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)


def _redirect_to_target_or_sessions(
    request: Request,
    return_to_value: str | None,
    *,
    notice: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    if not return_to_value or not return_to_value.startswith("/"):
        return _redirect_to_sessions(request, notice=notice, error=error)

    url = _append_query_params(
        return_to_value,
        {key: value for key, value in {"notice": notice, "error": error}.items() if value},
    )
    return RedirectResponse(url=url, status_code=status.HTTP_303_SEE_OTHER)


def _append_query_params(url: str, params: dict[str, str | int]) -> str:
    if not params:
        return url

    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    for key, value in params.items():
        query[key] = str(value)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
