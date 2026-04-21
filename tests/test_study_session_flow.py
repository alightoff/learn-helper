from __future__ import annotations

import os
from pathlib import Path
import shutil
import unittest
from urllib.parse import urlparse

from fastapi.testclient import TestClient

try:
    from alembic import command
    from alembic.config import Config
except ImportError:
    command = None
    Config = None

BASE_DIR = Path(__file__).resolve().parents[1]
RUNTIME_DIR = BASE_DIR / "data" / "test-runtime"

if RUNTIME_DIR.exists():
    shutil.rmtree(RUNTIME_DIR, ignore_errors=True)

os.environ["LEARN_HELPER_DATA_DIR"] = str(RUNTIME_DIR)
os.environ["LEARN_HELPER_DATABASE_URL"] = f"sqlite:///{(RUNTIME_DIR / 'app.db').as_posix()}"

from app.config import get_settings

get_settings.cache_clear()

from datetime import UTC, datetime, timedelta

from app.db.enums import OutlineSourceType, ProgressStatus, ResourceType, StudySessionStatus, TimerMode
from app.db.models import Base, Module, Resource, ResourceOutlineItem, StudySession
from app.db.session import SessionLocal, engine
from app.main import create_app


class StudySessionFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        if command is not None and Config is not None:
            alembic_config = Config(str(BASE_DIR / "alembic.ini"))
            command.upgrade(alembic_config, "head")
        else:
            Base.metadata.create_all(bind=engine)
        cls.client = TestClient(create_app())

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.close()
        engine.dispose()
        shutil.rmtree(RUNTIME_DIR, ignore_errors=True)

    def test_free_and_pomodoro_session_flow(self) -> None:
        sessions_page = self.client.get("/sessions")
        self.assertEqual(sessions_page.status_code, 200)
        self.assertIn("Start session", sessions_page.text)
        self.assertIn("Daily stats", sessions_page.text)

        create_course_response = self.client.post(
            "/courses",
            data={
                "title": "Systems Performance",
                "topic": "Benchmarking",
                "description": "Course used for session linkage.",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_course_response.status_code, 303)
        course_id = int(urlparse(create_course_response.headers["location"]).path.rstrip("/").split("/")[-1])

        create_module_response = self.client.post(
            f"/courses/{course_id}/modules",
            data={
                "title": "Latency",
                "description": "Module used for session linkage.",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_module_response.status_code, 303)

        with SessionLocal() as session:
            module = session.query(Module).filter(Module.course_id == course_id).one()
            resource = Resource(
                course_id=course_id,
                module_id=module.id,
                title="Latency Handbook",
                resource_type=ResourceType.PDF,
                file_path="courses/systems-performance/resources/module-1/latency-handbook.pdf",
                original_file_name="latency-handbook.pdf",
                mime_type="application/pdf",
                page_count=12,
            )
            session.add(resource)
            session.flush()
            outline_item = ResourceOutlineItem(
                resource_id=resource.id,
                title="Cache effects",
                position=0,
                page_number=3,
                source_type=OutlineSourceType.MANUAL,
            )
            session.add(outline_item)
            session.commit()
            resource_id = resource.id
            outline_item_id = outline_item.id
            module_id = module.id

        start_free_response = self.client.post(
            "/sessions/start",
            data={
                "session_type_value": "reading",
                "timer_mode_value": "free",
                "resource_id_value": str(resource_id),
                "outline_item_id_value": str(outline_item_id),
            },
            follow_redirects=False,
        )
        self.assertEqual(start_free_response.status_code, 303)
        self.assertIn(f"/resources/{resource_id}?page=3", start_free_response.headers["location"])

        with SessionLocal() as session:
            free_session = session.query(StudySession).order_by(StudySession.id.asc()).one()
            self.assertEqual(free_session.status, StudySessionStatus.RUNNING)
            self.assertEqual(free_session.timer_mode, TimerMode.FREE)
            self.assertEqual(free_session.course_id, course_id)
            self.assertEqual(free_session.module_id, module_id)
            self.assertEqual(free_session.resource_id, resource_id)
            self.assertEqual(free_session.outline_item_id, outline_item_id)
            self.assertIsNone(free_session.target_cycles)
            free_session.active_started_at = datetime.now(UTC) - timedelta(seconds=120)
            session.commit()
            free_session_id = free_session.id

        active_sessions_page = self.client.get("/sessions")
        self.assertEqual(active_sessions_page.status_code, 200)
        self.assertIn('data-session-status="running"', active_sessions_page.text)
        self.assertIn("Latency Handbook", active_sessions_page.text)
        self.assertIn("Cache effects (p. 3)", active_sessions_page.text)
        self.assertIn("Pause", active_sessions_page.text)

        pause_response = self.client.post(
            f"/sessions/{free_session_id}/pause",
            follow_redirects=False,
        )
        self.assertEqual(pause_response.status_code, 303)

        with SessionLocal() as session:
            paused_session = session.get(StudySession, free_session_id)
            self.assertEqual(paused_session.status, StudySessionStatus.PAUSED)
            self.assertIsNone(paused_session.active_started_at)
            self.assertGreaterEqual(int(paused_session.duration_seconds or 0), 120)

        resume_response = self.client.post(
            f"/sessions/{free_session_id}/resume",
            follow_redirects=False,
        )
        self.assertEqual(resume_response.status_code, 303)

        with SessionLocal() as session:
            resumed_session = session.get(StudySession, free_session_id)
            self.assertEqual(resumed_session.status, StudySessionStatus.RUNNING)
            resumed_session.active_started_at = datetime.now(UTC) - timedelta(seconds=30)
            session.commit()

        stop_free_response = self.client.post(
            f"/sessions/{free_session_id}/stop",
            follow_redirects=False,
        )
        self.assertEqual(stop_free_response.status_code, 303)

        with SessionLocal() as session:
            completed_free_session = session.get(StudySession, free_session_id)
            self.assertEqual(completed_free_session.status, StudySessionStatus.COMPLETED)
            self.assertIsNone(completed_free_session.active_started_at)
            self.assertIsNotNone(completed_free_session.ended_at)
            self.assertGreaterEqual(int(completed_free_session.duration_seconds or 0), 150)

        start_pomodoro_response = self.client.post(
            "/sessions/start",
            data={
                "session_type_value": "practice",
                "timer_mode_value": "pomodoro",
                "resource_id_value": str(resource_id),
                "outline_item_id_value": str(outline_item_id),
                "work_interval_minutes_value": "1",
                "break_interval_minutes_value": "1",
                "target_cycles_value": "1",
            },
            follow_redirects=False,
        )
        self.assertEqual(start_pomodoro_response.status_code, 303)
        self.assertIn(f"/resources/{resource_id}?page=3", start_pomodoro_response.headers["location"])

        with SessionLocal() as session:
            pomodoro_session = (
                session.query(StudySession)
                .filter(StudySession.id != free_session_id)
                .order_by(StudySession.id.desc())
                .one()
            )
            self.assertEqual(pomodoro_session.status, StudySessionStatus.RUNNING)
            self.assertEqual(pomodoro_session.timer_mode, TimerMode.POMODORO)
            self.assertEqual(pomodoro_session.resource_id, resource_id)
            self.assertEqual(pomodoro_session.outline_item_id, outline_item_id)
            self.assertEqual(pomodoro_session.work_interval_seconds, 60)
            self.assertEqual(pomodoro_session.break_interval_seconds, 60)
            self.assertEqual(pomodoro_session.target_cycles, 1)
            pomodoro_session.active_started_at = datetime.now(UTC) - timedelta(seconds=90)
            session.commit()
            pomodoro_session_id = pomodoro_session.id

        resource_page = self.client.get(f"/resources/{resource_id}?page=3")
        self.assertEqual(resource_page.status_code, 200)
        self.assertIn('data-resource-session-widget', resource_page.text)
        self.assertIn("Finish and rate", resource_page.text)
        self.assertIn("How did this session go?", resource_page.text)

        complete_pomodoro_response = self.client.post(
            f"/sessions/{pomodoro_session_id}/complete",
            data={
                "feedback_status_value": ProgressStatus.DONE.value,
                "page_number_value": "3",
                "return_to_value": f"/resources/{resource_id}?page=3#study-session-widget",
            },
            follow_redirects=False,
        )
        self.assertEqual(complete_pomodoro_response.status_code, 303)
        self.assertIn(f"/resources/{resource_id}?page=3", complete_pomodoro_response.headers["location"])

        with SessionLocal() as session:
            completed_pomodoro_session = session.get(StudySession, pomodoro_session_id)
            completed_outline_item = session.get(ResourceOutlineItem, outline_item_id)
            self.assertEqual(completed_pomodoro_session.status, StudySessionStatus.COMPLETED)
            self.assertEqual(completed_pomodoro_session.timer_mode, TimerMode.POMODORO)
            self.assertEqual(int(completed_pomodoro_session.duration_seconds or 0), 60)
            self.assertEqual(completed_pomodoro_session.cycles_completed, 1)
            self.assertEqual(completed_pomodoro_session.target_cycles, 1)
            self.assertEqual(completed_outline_item.status, ProgressStatus.DONE)

        final_sessions_page = self.client.get("/sessions")
        self.assertEqual(final_sessions_page.status_code, 200)
        self.assertIn("Systems Performance", final_sessions_page.text)
        self.assertIn("Latency Handbook", final_sessions_page.text)
        self.assertIn("Cache effects (p. 3)", final_sessions_page.text)
        self.assertIn("Pomodoro", final_sessions_page.text)
        self.assertIn("Plan 1 / 1", final_sessions_page.text)
        self.assertIn("03m 30s", final_sessions_page.text)
        self.assertIn("2 sessions", final_sessions_page.text)


if __name__ == "__main__":
    unittest.main()
