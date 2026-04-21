from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.enums import ProgressStatus, SessionType, StudySessionStatus, TimerMode
from app.db.models import Course, Resource, ResourceOutlineItem, StudySession
from app.services.progress import set_outline_item_status, set_page_status
from app.services.resources import get_resource_detail

SESSION_TYPE_OPTIONS: list[dict[str, str]] = [
    {"value": session_type.value, "label": session_type.value.replace("_", " ").title()}
    for session_type in SessionType
]

TIMER_MODE_OPTIONS: list[dict[str, str]] = [
    {"value": timer_mode.value, "label": timer_mode.value.replace("_", " ").title()}
    for timer_mode in TimerMode
]

ACTIVE_SESSION_STATUSES = (
    StudySessionStatus.RUNNING,
    StudySessionStatus.PAUSED,
)


class StudySessionError(Exception):
    """Raised when a study session action cannot be completed."""


def build_sessions_page_context(
    db: Session,
    *,
    history_limit: int = 20,
    stats_days: int = 7,
) -> dict[str, Any]:
    now = _utcnow()
    active_session = get_active_study_session(db)
    history_sessions = list_study_sessions(db, limit=history_limit)
    stats_sessions = list_study_sessions(db, limit=None)
    resource_options, outline_item_groups = build_session_scope_options(db)

    return {
        "active_session": build_session_view(active_session, now=now) if active_session is not None else None,
        "session_history": [build_session_view(session, now=now) for session in history_sessions],
        "daily_stats": build_daily_stats(stats_sessions, now=now, days=stats_days),
        "resource_options": resource_options,
        "outline_item_groups": outline_item_groups,
        "session_type_options": SESSION_TYPE_OPTIONS,
        "timer_mode_options": TIMER_MODE_OPTIONS,
    }


def build_session_scope_options(db: Session) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    resources = list_session_resources(db)
    resource_options: list[dict[str, Any]] = []
    outline_item_groups: list[dict[str, Any]] = []

    for resource in resources:
        resource_label = _build_resource_label(resource)
        resource_options.append(
            {
                "id": resource.id,
                "label": resource_label,
            }
        )

        outline_items = sorted(resource.outline_items, key=lambda item: (item.position, item.id))
        if not outline_items:
            continue

        outline_item_groups.append(
            {
                "resource_id": resource.id,
                "resource_label": resource_label,
                "options": [
                    {
                        "id": item.id,
                        "label": _build_outline_item_label(item),
                    }
                    for item in outline_items
                ],
            }
        )

    return resource_options, outline_item_groups


def list_session_resources(db: Session) -> list[Resource]:
    statement = (
        select(Resource)
        .join(Course, Resource.course_id == Course.id)
        .options(
            selectinload(Resource.course),
            selectinload(Resource.outline_items),
        )
        .order_by(Course.title.asc(), Resource.title.asc(), Resource.id.asc())
    )
    return list(db.scalars(statement))


def get_active_study_session(db: Session) -> StudySession | None:
    statement = (
        select(StudySession)
        .where(StudySession.status.in_(ACTIVE_SESSION_STATUSES))
        .options(
            selectinload(StudySession.course),
            selectinload(StudySession.resource),
            selectinload(StudySession.outline_item),
        )
        .order_by(StudySession.started_at.desc(), StudySession.id.desc())
    )
    return db.scalar(statement)


def list_study_sessions(db: Session, *, limit: int | None) -> list[StudySession]:
    statement = (
        select(StudySession)
        .options(
            selectinload(StudySession.course),
            selectinload(StudySession.resource),
            selectinload(StudySession.outline_item),
        )
        .order_by(StudySession.started_at.desc(), StudySession.id.desc())
    )
    if limit is not None:
        statement = statement.limit(limit)
    return list(db.scalars(statement))


def start_study_session(
    db: Session,
    *,
    session_type: SessionType,
    timer_mode: TimerMode,
    resource_id: int | None = None,
    outline_item_id: int | None = None,
    work_interval_minutes: int | None = None,
    break_interval_minutes: int | None = None,
    target_cycles: int | None = None,
) -> StudySession:
    if get_active_study_session(db) is not None:
        raise StudySessionError("Finish or stop the current session before starting another one.")

    course, resource, outline_item = _resolve_session_scope(
        db,
        resource_id=resource_id,
        outline_item_id=outline_item_id,
    )
    work_interval_seconds, break_interval_seconds = _resolve_timer_intervals(
        timer_mode=timer_mode,
        work_interval_minutes=work_interval_minutes,
        break_interval_minutes=break_interval_minutes,
    )

    if timer_mode == TimerMode.POMODORO and target_cycles is None:
        raise StudySessionError("Choose how many pomodoro cycles you plan to do.")
    if timer_mode != TimerMode.POMODORO:
        target_cycles = None

    now = _utcnow()
    study_session = StudySession(
        course_id=course.id if course is not None else None,
        module_id=resource.module_id if resource is not None else None,
        resource_id=resource.id if resource is not None else None,
        outline_item_id=outline_item.id if outline_item is not None else None,
        session_type=session_type,
        timer_mode=timer_mode,
        status=StudySessionStatus.RUNNING,
        started_at=now,
        active_started_at=now,
        duration_seconds=0,
        work_interval_seconds=work_interval_seconds,
        break_interval_seconds=break_interval_seconds,
        cycles_completed=0,
        target_cycles=target_cycles,
    )
    db.add(study_session)
    db.commit()
    db.refresh(study_session)
    return study_session


def pause_study_session(db: Session, *, session_id: int) -> StudySession:
    study_session = _get_session_for_update(db, session_id)
    if study_session.status != StudySessionStatus.RUNNING:
        raise StudySessionError("Only a running session can be paused.")
    if _session_needs_feedback(study_session):
        raise StudySessionError("Pomodoro cycles already finished. Rate the session or stop it.")

    study_session.duration_seconds = calculate_elapsed_seconds(study_session)
    study_session.active_started_at = None
    study_session.status = StudySessionStatus.PAUSED
    db.commit()
    db.refresh(study_session)
    return study_session


def resume_study_session(db: Session, *, session_id: int) -> StudySession:
    study_session = _get_session_for_update(db, session_id)
    if study_session.status != StudySessionStatus.PAUSED:
        raise StudySessionError("Only a paused session can be resumed.")

    if get_active_study_session(db) not in (None, study_session):
        raise StudySessionError("Another active session is already open.")

    study_session.active_started_at = _utcnow()
    study_session.status = StudySessionStatus.RUNNING
    db.commit()
    db.refresh(study_session)
    return study_session


def stop_study_session(db: Session, *, session_id: int) -> StudySession:
    study_session = _get_session_for_update(db, session_id)
    if study_session.status not in ACTIVE_SESSION_STATUSES:
        raise StudySessionError("Only an active session can be stopped.")

    _finalize_study_session(db, study_session)
    db.commit()
    db.refresh(study_session)
    return study_session


def complete_study_session_with_feedback(
    db: Session,
    *,
    session_id: int,
    feedback_status: ProgressStatus | None = None,
    page_number: int | None = None,
) -> StudySession:
    study_session = _get_session_for_update(db, session_id)
    if study_session.status not in ACTIVE_SESSION_STATUSES:
        raise StudySessionError("Only an active session can be completed.")

    _finalize_study_session(db, study_session)
    db.commit()
    db.refresh(study_session)

    if feedback_status is None or study_session.resource_id is None:
        return _reload_study_session(db, study_session.id)

    resource = get_resource_detail(db, study_session.resource_id)
    if resource is None:
        return _reload_study_session(db, study_session.id)

    if study_session.outline_item_id is not None:
        set_outline_item_status(
            db,
            resource=resource,
            outline_item_id=study_session.outline_item_id,
            status=feedback_status,
        )
        return _reload_study_session(db, study_session.id)

    if not resource.outline_items and page_number is not None:
        set_page_status(
            db,
            resource=resource,
            page_number=page_number,
            status=feedback_status,
        )

    return _reload_study_session(db, study_session.id)


def build_session_view(study_session: StudySession, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or _utcnow()
    elapsed_seconds = calculate_elapsed_seconds(study_session, now=now)
    pomodoro = None
    if study_session.timer_mode == TimerMode.POMODORO:
        pomodoro = build_pomodoro_view(
            elapsed_seconds=elapsed_seconds,
            work_interval_seconds=study_session.work_interval_seconds,
            break_interval_seconds=study_session.break_interval_seconds,
            target_cycles=study_session.target_cycles,
        )

    course_title = study_session.course.title if study_session.course is not None else "General session"
    resource_title = study_session.resource.title if study_session.resource is not None else None
    outline_item_title = (
        _build_outline_item_label(study_session.outline_item)
        if study_session.outline_item is not None
        else None
    )
    needs_feedback = bool(
        study_session.status in ACTIVE_SESSION_STATUSES
        and pomodoro is not None
        and pomodoro["is_complete"]
    )

    return {
        "id": study_session.id,
        "status": study_session.status,
        "status_label": study_session.status.value.title(),
        "session_type": study_session.session_type,
        "session_type_label": study_session.session_type.value.replace("_", " ").title(),
        "timer_mode": study_session.timer_mode,
        "timer_mode_label": study_session.timer_mode.value.replace("_", " ").title(),
        "course_title": course_title,
        "resource_title": resource_title,
        "outline_item_title": outline_item_title,
        "focus_label": _build_focus_label(resource_title=resource_title, outline_item_title=outline_item_title),
        "started_at_label": format_datetime(study_session.started_at),
        "ended_at_label": format_datetime(study_session.ended_at),
        "elapsed_seconds": elapsed_seconds,
        "elapsed_label": format_duration(elapsed_seconds),
        "work_interval_label": format_duration(study_session.work_interval_seconds),
        "break_interval_label": format_duration(study_session.break_interval_seconds),
        "cycles_completed": study_session.cycles_completed or 0,
        "target_cycles": study_session.target_cycles,
        "target_cycles_label": _format_target_cycles_label(study_session.target_cycles),
        "resource_id": study_session.resource_id,
        "outline_item_id": study_session.outline_item_id,
        "resource_page_target": _resolve_session_page_target(study_session),
        "is_running": study_session.status == StudySessionStatus.RUNNING,
        "is_paused": study_session.status == StudySessionStatus.PAUSED,
        "is_completed": study_session.status == StudySessionStatus.COMPLETED,
        "needs_feedback": needs_feedback,
        "can_pause": study_session.status == StudySessionStatus.RUNNING and not needs_feedback,
        "can_resume": study_session.status == StudySessionStatus.PAUSED,
        "active_started_at_iso": to_isoformat(study_session.active_started_at),
        "pomodoro": pomodoro,
    }


def build_daily_stats(
    sessions: Sequence[StudySession],
    *,
    now: datetime,
    days: int,
) -> list[dict[str, Any]]:
    stats_by_day: dict[date, dict[str, int]] = defaultdict(lambda: {"total_seconds": 0, "session_count": 0})
    for session in sessions:
        session_day = _as_utc(session.started_at).date()
        stats_by_day[session_day]["total_seconds"] += calculate_elapsed_seconds(session, now=now)
        stats_by_day[session_day]["session_count"] += 1

    rows: list[dict[str, Any]] = []
    today = now.date()
    for day_offset in range(days):
        current_day = today - timedelta(days=day_offset)
        stats_row = stats_by_day[current_day]
        rows.append(
            {
                "date": current_day,
                "date_label": current_day.strftime("%Y-%m-%d"),
                "total_seconds": stats_row["total_seconds"],
                "total_label": format_duration(stats_row["total_seconds"]),
                "session_count": stats_row["session_count"],
            }
        )
    return rows


def build_pomodoro_view(
    *,
    elapsed_seconds: int,
    work_interval_seconds: int | None,
    break_interval_seconds: int | None,
    target_cycles: int | None,
) -> dict[str, Any] | None:
    pomodoro_state = resolve_pomodoro_state(
        elapsed_seconds=elapsed_seconds,
        work_interval_seconds=work_interval_seconds,
        break_interval_seconds=break_interval_seconds,
        target_cycles=target_cycles,
    )
    if pomodoro_state is None:
        return None

    return {
        **pomodoro_state,
        "phase_remaining_label": format_duration(pomodoro_state["phase_remaining_seconds"]),
        "target_cycles_label": _format_target_cycles_label(target_cycles),
        "target_progress_label": _format_target_progress_label(
            pomodoro_state["completed_cycles"],
            target_cycles,
        ),
        "planned_total_label": format_duration(pomodoro_state["planned_total_seconds"]),
        "work_interval_seconds": work_interval_seconds,
        "break_interval_seconds": max(break_interval_seconds or 0, 0),
    }


def resolve_pomodoro_state(
    *,
    elapsed_seconds: int,
    work_interval_seconds: int | None,
    break_interval_seconds: int | None,
    target_cycles: int | None,
) -> dict[str, Any] | None:
    if work_interval_seconds is None or work_interval_seconds <= 0:
        return None

    safe_break_seconds = max(break_interval_seconds or 0, 0)
    bounded_elapsed_seconds = max(int(elapsed_seconds), 0)

    if target_cycles is not None:
        total_planned_seconds = calculate_planned_total_seconds(
            timer_mode=TimerMode.POMODORO,
            work_interval_seconds=work_interval_seconds,
            break_interval_seconds=safe_break_seconds,
            target_cycles=target_cycles,
        ) or 0
        bounded_elapsed_seconds = min(bounded_elapsed_seconds, total_planned_seconds)
        remaining_seconds = bounded_elapsed_seconds

        for cycle_index in range(1, target_cycles + 1):
            if remaining_seconds < work_interval_seconds:
                return {
                    "phase": "work",
                    "phase_label": "Work",
                    "phase_remaining_seconds": work_interval_seconds - remaining_seconds,
                    "current_cycle": cycle_index,
                    "completed_cycles": cycle_index - 1,
                    "cycle_label": f"Cycle {cycle_index}",
                    "is_complete": False,
                    "planned_total_seconds": total_planned_seconds,
                    "target_cycles": target_cycles,
                }

            remaining_seconds -= work_interval_seconds
            completed_cycles = cycle_index

            if cycle_index == target_cycles:
                return {
                    "phase": "complete",
                    "phase_label": "Complete",
                    "phase_remaining_seconds": 0,
                    "current_cycle": cycle_index,
                    "completed_cycles": completed_cycles,
                    "cycle_label": f"Cycle {cycle_index}",
                    "is_complete": True,
                    "planned_total_seconds": total_planned_seconds,
                    "target_cycles": target_cycles,
                }

            if safe_break_seconds > 0:
                if remaining_seconds < safe_break_seconds:
                    next_cycle = cycle_index + 1
                    return {
                        "phase": "break",
                        "phase_label": "Break",
                        "phase_remaining_seconds": safe_break_seconds - remaining_seconds,
                        "current_cycle": next_cycle,
                        "completed_cycles": completed_cycles,
                        "cycle_label": f"Cycle {next_cycle}",
                        "is_complete": False,
                        "planned_total_seconds": total_planned_seconds,
                        "target_cycles": target_cycles,
                    }
                remaining_seconds -= safe_break_seconds

        return {
            "phase": "complete",
            "phase_label": "Complete",
            "phase_remaining_seconds": 0,
            "current_cycle": target_cycles,
            "completed_cycles": target_cycles,
            "cycle_label": f"Cycle {target_cycles}",
            "is_complete": True,
            "planned_total_seconds": total_planned_seconds,
            "target_cycles": target_cycles,
        }

    cycle_length = max(work_interval_seconds + safe_break_seconds, work_interval_seconds)
    cycle_index = (bounded_elapsed_seconds // cycle_length) + 1
    cycle_offset = bounded_elapsed_seconds % cycle_length

    if safe_break_seconds > 0 and cycle_offset >= work_interval_seconds:
        phase = "break"
        phase_label = "Break"
        phase_elapsed = cycle_offset - work_interval_seconds
        phase_duration = safe_break_seconds
    else:
        phase = "work"
        phase_label = "Work"
        phase_elapsed = cycle_offset
        phase_duration = work_interval_seconds

    completed_cycles = 0
    if bounded_elapsed_seconds >= work_interval_seconds:
        completed_cycles = 1 + max(bounded_elapsed_seconds - work_interval_seconds, 0) // cycle_length

    return {
        "phase": phase,
        "phase_label": phase_label,
        "phase_remaining_seconds": max(phase_duration - phase_elapsed, 0),
        "current_cycle": cycle_index,
        "completed_cycles": completed_cycles,
        "cycle_label": f"Cycle {cycle_index}",
        "is_complete": False,
        "planned_total_seconds": cycle_length,
        "target_cycles": None,
    }


def calculate_elapsed_seconds(study_session: StudySession, *, now: datetime | None = None) -> int:
    now = now or _utcnow()
    elapsed_seconds = max(int(study_session.duration_seconds or 0), 0)
    if study_session.status == StudySessionStatus.RUNNING and study_session.active_started_at is not None:
        active_started_at = _as_utc(study_session.active_started_at)
        elapsed_seconds += max(int((now - active_started_at).total_seconds()), 0)

    planned_total_seconds = calculate_planned_total_seconds(
        timer_mode=study_session.timer_mode,
        work_interval_seconds=study_session.work_interval_seconds,
        break_interval_seconds=study_session.break_interval_seconds,
        target_cycles=study_session.target_cycles,
    )
    if planned_total_seconds is not None:
        return min(elapsed_seconds, planned_total_seconds)
    return elapsed_seconds


def compute_completed_cycles(
    *,
    timer_mode: TimerMode,
    elapsed_seconds: int,
    work_interval_seconds: int | None,
    break_interval_seconds: int | None,
    target_cycles: int | None = None,
) -> int:
    pomodoro_state = resolve_pomodoro_state(
        elapsed_seconds=elapsed_seconds,
        work_interval_seconds=work_interval_seconds,
        break_interval_seconds=break_interval_seconds,
        target_cycles=target_cycles,
    )
    if timer_mode != TimerMode.POMODORO or pomodoro_state is None:
        return 0
    return int(pomodoro_state["completed_cycles"])


def calculate_planned_total_seconds(
    *,
    timer_mode: TimerMode,
    work_interval_seconds: int | None,
    break_interval_seconds: int | None,
    target_cycles: int | None,
) -> int | None:
    if timer_mode != TimerMode.POMODORO:
        return None
    if work_interval_seconds is None or work_interval_seconds <= 0:
        return None
    if target_cycles is None or target_cycles <= 0:
        return None

    safe_break_seconds = max(break_interval_seconds or 0, 0)
    return (target_cycles * work_interval_seconds) + (max(target_cycles - 1, 0) * safe_break_seconds)


def parse_session_type(value: str) -> SessionType:
    try:
        return SessionType(value)
    except ValueError as exc:
        raise StudySessionError("Unknown session type.") from exc


def parse_timer_mode(value: str) -> TimerMode:
    try:
        return TimerMode(value)
    except ValueError as exc:
        raise StudySessionError("Unknown timer mode.") from exc


def parse_optional_resource_id(value: str | None) -> int | None:
    return _parse_optional_positive_int(value, field_label="Resource id")


def parse_optional_outline_item_id(value: str | None) -> int | None:
    return _parse_optional_positive_int(value, field_label="Outline item id")


def parse_optional_target_cycles(value: str | None) -> int | None:
    return _parse_optional_positive_int(value, field_label="Target cycles")


def parse_optional_page_number(value: str | None) -> int | None:
    return _parse_optional_positive_int(value, field_label="Page number")


def parse_optional_minutes(value: str | None, *, field_label: str) -> int | None:
    if value is None or not value.strip():
        return None
    try:
        minutes = int(value)
    except ValueError as exc:
        raise StudySessionError(f"{field_label} must be a whole number.") from exc
    if minutes < 0:
        raise StudySessionError(f"{field_label} cannot be negative.")
    return minutes


def format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "n/a"
    total_seconds = max(int(seconds), 0)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds_part = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h {minutes:02d}m {seconds_part:02d}s"
    return f"{minutes:02d}m {seconds_part:02d}s"


def format_datetime(value: datetime | None) -> str:
    if value is None:
        return "Still active"
    return _as_utc(value).strftime("%Y-%m-%d %H:%M:%S")


def to_isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _as_utc(value).isoformat()


def _resolve_timer_intervals(
    *,
    timer_mode: TimerMode,
    work_interval_minutes: int | None,
    break_interval_minutes: int | None,
) -> tuple[int | None, int | None]:
    if timer_mode == TimerMode.FREE:
        return None, None

    work_minutes = work_interval_minutes if work_interval_minutes is not None else 25
    break_minutes = break_interval_minutes if break_interval_minutes is not None else 5

    if work_minutes <= 0:
        raise StudySessionError("Pomodoro work interval must be greater than zero.")
    if break_minutes < 0:
        raise StudySessionError("Pomodoro break interval cannot be negative.")
    return work_minutes * 60, break_minutes * 60


def _resolve_session_scope(
    db: Session,
    *,
    resource_id: int | None,
    outline_item_id: int | None,
) -> tuple[Course | None, Resource | None, ResourceOutlineItem | None]:
    resource: Resource | None = None
    outline_item: ResourceOutlineItem | None = None

    if resource_id is not None:
        resource = db.scalar(
            select(Resource)
            .where(Resource.id == resource_id)
            .options(selectinload(Resource.course))
        )
        if resource is None:
            raise StudySessionError("Selected resource was not found.")

    if outline_item_id is not None:
        outline_item = db.scalar(
            select(ResourceOutlineItem)
            .where(ResourceOutlineItem.id == outline_item_id)
            .options(selectinload(ResourceOutlineItem.resource).selectinload(Resource.course))
        )
        if outline_item is None:
            raise StudySessionError("Selected outline item was not found.")

    if outline_item is not None and resource is not None and outline_item.resource_id != resource.id:
        raise StudySessionError("Selected outline item does not belong to the selected resource.")

    if outline_item is not None and resource is None:
        resource = outline_item.resource

    course = resource.course if resource is not None else None
    return course, resource, outline_item


def _finalize_study_session(db: Session, study_session: StudySession) -> None:
    now = _utcnow()
    final_elapsed_seconds = calculate_elapsed_seconds(study_session, now=now)
    study_session.duration_seconds = final_elapsed_seconds
    study_session.active_started_at = None
    study_session.ended_at = now
    study_session.status = StudySessionStatus.COMPLETED
    study_session.cycles_completed = compute_completed_cycles(
        timer_mode=study_session.timer_mode,
        elapsed_seconds=final_elapsed_seconds,
        work_interval_seconds=study_session.work_interval_seconds,
        break_interval_seconds=study_session.break_interval_seconds,
        target_cycles=study_session.target_cycles,
    )


def _session_needs_feedback(study_session: StudySession) -> bool:
    pomodoro_state = resolve_pomodoro_state(
        elapsed_seconds=calculate_elapsed_seconds(study_session),
        work_interval_seconds=study_session.work_interval_seconds,
        break_interval_seconds=study_session.break_interval_seconds,
        target_cycles=study_session.target_cycles,
    )
    return bool(
        study_session.timer_mode == TimerMode.POMODORO
        and pomodoro_state is not None
        and pomodoro_state["is_complete"]
    )


def _get_session_for_update(db: Session, session_id: int) -> StudySession:
    study_session = db.scalar(
        select(StudySession)
        .where(StudySession.id == session_id)
        .options(
            selectinload(StudySession.course),
            selectinload(StudySession.resource),
            selectinload(StudySession.outline_item),
        )
    )
    if study_session is None:
        raise StudySessionError("Study session was not found.")
    return study_session


def _reload_study_session(db: Session, session_id: int) -> StudySession:
    study_session = db.scalar(
        select(StudySession)
        .where(StudySession.id == session_id)
        .options(
            selectinload(StudySession.course),
            selectinload(StudySession.resource),
            selectinload(StudySession.outline_item),
        )
    )
    if study_session is None:
        raise StudySessionError("Study session was not found.")
    return study_session


def _resolve_session_page_target(study_session: StudySession) -> int:
    if study_session.outline_item is not None and study_session.outline_item.page_number is not None:
        return study_session.outline_item.page_number
    return 1


def _build_resource_label(resource: Resource) -> str:
    course_title = resource.course.title if resource.course is not None else "Untitled course"
    return f"{course_title} / {resource.title}"


def _build_outline_item_label(outline_item: ResourceOutlineItem) -> str:
    if outline_item.page_number is None:
        return outline_item.title
    return f"{outline_item.title} (p. {outline_item.page_number})"


def _build_focus_label(*, resource_title: str | None, outline_item_title: str | None) -> str | None:
    parts = [part for part in (resource_title, outline_item_title) if part]
    if not parts:
        return None
    return " -> ".join(parts)


def _format_target_cycles_label(target_cycles: int | None) -> str | None:
    if target_cycles is None:
        return None
    return f"{target_cycles} cycle{'s' if target_cycles != 1 else ''}"


def _format_target_progress_label(completed_cycles: int, target_cycles: int | None) -> str | None:
    if target_cycles is None:
        return None
    return f"{completed_cycles} / {target_cycles}"


def _parse_optional_positive_int(value: str | None, *, field_label: str) -> int | None:
    if value is None or not value.strip():
        return None
    try:
        parsed_value = int(value)
    except ValueError as exc:
        raise StudySessionError(f"{field_label} must be numeric.") from exc
    if parsed_value <= 0:
        raise StudySessionError(f"{field_label} must be positive.")
    return parsed_value


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
