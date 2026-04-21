from __future__ import annotations

import io
import os
from pathlib import Path
import shutil
import unittest
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parents[1]
from fastapi.testclient import TestClient
from pypdf import PdfWriter

try:
    from alembic import command
    from alembic.config import Config
except ImportError:
    command = None
    Config = None

RUNTIME_DIR = BASE_DIR / "data" / "test-runtime"

if RUNTIME_DIR.exists():
    shutil.rmtree(RUNTIME_DIR, ignore_errors=True)

os.environ["LEARN_HELPER_DATA_DIR"] = str(RUNTIME_DIR)
os.environ["LEARN_HELPER_DATABASE_URL"] = f"sqlite:///{(RUNTIME_DIR / 'app.db').as_posix()}"

from app.config import get_settings

get_settings.cache_clear()

from app.db.enums import ProgressStatus
from app.db.models import Anchor, Base, Module, ProgressRecord, Resource, ResourceOutlineItem
from app.db.session import SessionLocal, engine
from app.main import create_app


class PdfImportFlowTest(unittest.TestCase):
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

    def test_pdf_import_flow_with_and_without_outline(self) -> None:
        create_course_response = self.client.post(
            "/courses",
            data={
                "title": "Reverse Engineering",
                "topic": "Binary analysis",
                "description": "Course used for PDF import verification.",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_course_response.status_code, 303)

        course_location = urlparse(create_course_response.headers["location"]).path
        self.assertTrue(course_location.startswith("/courses/"))
        course_id = int(course_location.rstrip("/").split("/")[-1])

        create_module_response = self.client.post(
            f"/courses/{course_id}/modules",
            data={
                "title": "Reading queue",
                "description": "Imported PDFs land here.",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_module_response.status_code, 303)

        with SessionLocal() as session:
            module = session.query(Module).one()
            module_id = module.id

        import_with_outline_response = self.client.post(
            f"/modules/{module_id}/resources/pdf",
            data={
                "title": "Outline PDF",
                "description": "Should produce parsed outline items.",
            },
            files={
                "file": (
                    "outline.pdf",
                    _build_pdf_bytes(with_outline=True),
                    "application/pdf",
                )
            },
            follow_redirects=False,
        )
        self.assertEqual(import_with_outline_response.status_code, 303)

        import_without_outline_response = self.client.post(
            f"/modules/{module_id}/resources/pdf",
            data={
                "title": "No Outline PDF",
                "description": "Should still import cleanly.",
            },
            files={
                "file": (
                    "no-outline.pdf",
                    _build_pdf_bytes(with_outline=False),
                    "application/pdf",
                )
            },
            follow_redirects=False,
        )
        self.assertEqual(import_without_outline_response.status_code, 303)

        import_long_outline_response = self.client.post(
            f"/modules/{module_id}/resources/pdf",
            data={
                "title": "Long Outline PDF",
                "description": "Should collapse long parsed outlines on the course page.",
            },
            files={
                "file": (
                    "long-outline.pdf",
                    _build_pdf_bytes(
                        with_outline=True,
                        outline_titles=[f"Chapter {index}" for index in range(1, 13)],
                    ),
                    "application/pdf",
                )
            },
            follow_redirects=False,
        )
        self.assertEqual(import_long_outline_response.status_code, 303)

        course_page = self.client.get(f"/courses/{course_id}")
        self.assertEqual(course_page.status_code, 200)
        self.assertIn("Outline PDF", course_page.text)
        self.assertIn("No Outline PDF", course_page.text)
        self.assertIn("Long Outline PDF", course_page.text)
        self.assertIn("2 pages", course_page.text)
        self.assertIn("Intro", course_page.text)
        self.assertIn("Deep Dive", course_page.text)
        self.assertIn("Outline was not found", course_page.text)
        self.assertIn("Show more", course_page.text)
        self.assertIn("outline-tree__item--collapsed", course_page.text)

        with SessionLocal() as session:
            resources = session.query(Resource).order_by(Resource.id).all()
            outline_items = session.query(ResourceOutlineItem).order_by(ResourceOutlineItem.id).all()

            self.assertEqual(len(resources), 3)
            self.assertEqual(resources[0].page_count, 2)
            self.assertEqual(resources[1].page_count, 2)
            self.assertEqual(resources[2].page_count, 2)

            outlined_resource = next(resource for resource in resources if resource.title == "Outline PDF")
            plain_resource = next(resource for resource in resources if resource.title == "No Outline PDF")
            long_outline_resource = next(resource for resource in resources if resource.title == "Long Outline PDF")
            outlined_items = [item for item in outline_items if item.resource_id == outlined_resource.id]
            plain_items = [item for item in outline_items if item.resource_id == plain_resource.id]
            long_outline_items = [item for item in outline_items if item.resource_id == long_outline_resource.id]

            self.assertEqual(len(outlined_items), 2)
            self.assertEqual(len(plain_items), 0)
            self.assertEqual(len(long_outline_items), 12)

            root_item = next(item for item in outlined_items if item.parent_id is None)
            child_item = next(item for item in outlined_items if item.parent_id == root_item.id)

            self.assertEqual(root_item.title, "Intro")
            self.assertEqual(root_item.page_number, 1)
            self.assertEqual(child_item.title, "Deep Dive")
            self.assertEqual(child_item.page_number, 2)

            viewer_response = self.client.get(f"/resources/{outlined_resource.id}?page=2")
            self.assertEqual(viewer_response.status_code, 200)
            self.assertIn("data-pdf-resource-viewer", viewer_response.text)
            self.assertIn('data-initial-page="2"', viewer_response.text)
            self.assertIn("Resource status", viewer_response.text)
            self.assertIn("Open original file", viewer_response.text)
            self.assertIn('data-outline-page="1"', viewer_response.text)
            self.assertIn('data-outline-page="2"', viewer_response.text)
            self.assertIn(f'/resources/{outlined_resource.id}?page=2#pdf-reader', viewer_response.text)

            plain_viewer_response = self.client.get(f"/resources/{plain_resource.id}")
            self.assertEqual(plain_viewer_response.status_code, 200)
            self.assertIn("No outline extracted yet.", plain_viewer_response.text)

            self.assertIn(f"/resources/{outlined_resource.id}", course_page.text)

            viewer_script_response = self.client.get("/static/js/pdf_resource_viewer.js")
            pdfjs_bundle_response = self.client.get("/static/vendor/pdfjs/legacy/build/pdf.mjs")
            pdfjs_worker_response = self.client.get("/static/vendor/pdfjs/legacy/build/pdf.worker.mjs")

            self.assertEqual(viewer_script_response.status_code, 200)
            self.assertEqual(pdfjs_bundle_response.status_code, 200)
            self.assertEqual(pdfjs_worker_response.status_code, 200)
            self.assertIn("javascript", viewer_script_response.headers.get("content-type", ""))
            self.assertIn("javascript", pdfjs_bundle_response.headers.get("content-type", ""))
            self.assertIn("javascript", pdfjs_worker_response.headers.get("content-type", ""))

            outlined_file_response = self.client.get(f"/uploads/{outlined_resource.file_path}")
            plain_file_response = self.client.get(f"/uploads/{plain_resource.file_path}")

            self.assertEqual(outlined_file_response.status_code, 200)
            self.assertEqual(plain_file_response.status_code, 200)
            self.assertGreater(len(outlined_file_response.content), 0)
            self.assertGreater(len(plain_file_response.content), 0)

    def test_progress_status_flow_for_outline_and_page_fallback(self) -> None:
        create_course_response = self.client.post(
            "/courses",
            data={
                "title": "Applied Cryptography",
                "topic": "Protocols",
                "description": "Course used for progress aggregation checks.",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_course_response.status_code, 303)
        course_id = int(urlparse(create_course_response.headers["location"]).path.rstrip("/").split("/")[-1])

        create_module_response = self.client.post(
            f"/courses/{course_id}/modules",
            data={
                "title": "Week 1",
                "description": "Progress target module.",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_module_response.status_code, 303)

        with SessionLocal() as session:
            module = session.query(Module).filter(Module.course_id == course_id).one()
            module_id = module.id

        outline_import_response = self.client.post(
            f"/modules/{module_id}/resources/pdf",
            data={
                "title": "Outline Progress PDF",
                "description": "Needs outline-item progress.",
            },
            files={
                "file": (
                    "outline-progress.pdf",
                    _build_pdf_bytes(with_outline=True),
                    "application/pdf",
                )
            },
            follow_redirects=False,
        )
        self.assertEqual(outline_import_response.status_code, 303)

        plain_import_response = self.client.post(
            f"/modules/{module_id}/resources/pdf",
            data={
                "title": "Page Progress PDF",
                "description": "Needs page fallback progress.",
            },
            files={
                "file": (
                    "page-progress.pdf",
                    _build_pdf_bytes(with_outline=False),
                    "application/pdf",
                )
            },
            follow_redirects=False,
        )
        self.assertEqual(plain_import_response.status_code, 303)

        with SessionLocal() as session:
            outlined_resource = session.query(Resource).filter(Resource.title == "Outline Progress PDF").one()
            plain_resource = session.query(Resource).filter(Resource.title == "Page Progress PDF").one()
            outlined_items = (
                session.query(ResourceOutlineItem)
                .filter(ResourceOutlineItem.resource_id == outlined_resource.id)
                .order_by(ResourceOutlineItem.id)
                .all()
            )
            root_item = next(item for item in outlined_items if item.parent_id is None)
            child_item = next(item for item in outlined_items if item.parent_id == root_item.id)

        root_in_progress_response = self.client.post(
            f"/resources/{outlined_resource.id}/outline-items/{root_item.id}/status",
            data={
                "status_value": ProgressStatus.IN_PROGRESS.value,
                "return_page": 1,
                "redirect_anchor": f"outline-item-{root_item.id}",
            },
            follow_redirects=False,
        )
        self.assertEqual(root_in_progress_response.status_code, 303)

        root_done_response = self.client.post(
            f"/resources/{outlined_resource.id}/outline-items/{root_item.id}/status",
            data={
                "status_value": ProgressStatus.DONE.value,
                "return_page": 1,
                "redirect_anchor": f"outline-item-{root_item.id}",
            },
            follow_redirects=False,
        )
        self.assertEqual(root_done_response.status_code, 303)

        child_review_response = self.client.post(
            f"/resources/{outlined_resource.id}/outline-items/{child_item.id}/status",
            data={
                "status_value": ProgressStatus.REVIEW.value,
                "return_page": 2,
                "redirect_anchor": f"outline-item-{child_item.id}",
            },
            follow_redirects=False,
        )
        self.assertEqual(child_review_response.status_code, 303)

        page_hard_response = self.client.post(
            f"/resources/{plain_resource.id}/pages/status",
            data={
                "page_number": 2,
                "status_value": ProgressStatus.HARD.value,
                "redirect_anchor": "page-progress-panel",
            },
            follow_redirects=False,
        )
        self.assertEqual(page_hard_response.status_code, 303)

        with SessionLocal() as session:
            refreshed_root = session.get(ResourceOutlineItem, root_item.id)
            refreshed_child = session.get(ResourceOutlineItem, child_item.id)
            root_records = (
                session.query(ProgressRecord)
                .filter(ProgressRecord.outline_item_id == root_item.id)
                .all()
            )
            page_anchor = (
                session.query(Anchor)
                .filter(
                    Anchor.resource_id == plain_resource.id,
                    Anchor.page_number == 2,
                )
                .one()
            )
            page_record = (
                session.query(ProgressRecord)
                .filter(ProgressRecord.anchor_id == page_anchor.id)
                .one()
            )

            self.assertEqual(refreshed_root.status, ProgressStatus.DONE)
            self.assertEqual(refreshed_child.status, ProgressStatus.REVIEW)
            self.assertEqual(len(root_records), 1)
            self.assertEqual(root_records[0].status, ProgressStatus.DONE)
            self.assertEqual(page_record.status, ProgressStatus.HARD)

        course_page = self.client.get(f"/courses/{course_id}")
        self.assertEqual(course_page.status_code, 200)
        self.assertIn('id="course-progress-summary"', course_page.text)
        self.assertIn('data-progress-percent="50"', course_page.text)
        self.assertIn('data-progress-status="hard"', course_page.text)
        self.assertIn(f'id="resource-progress-{outlined_resource.id}"', course_page.text)
        self.assertIn('data-progress-percent="88"', course_page.text)
        self.assertIn('data-progress-status="review"', course_page.text)
        self.assertIn(f'id="resource-progress-{plain_resource.id}"', course_page.text)
        self.assertIn('data-progress-percent="13"', course_page.text)
        self.assertIn('data-progress-status="hard"', course_page.text)

        outlined_viewer_response = self.client.get(f"/resources/{outlined_resource.id}?page=2")
        self.assertEqual(outlined_viewer_response.status_code, 200)
        self.assertIn('id="resource-study-progress"', outlined_viewer_response.text)
        self.assertIn('data-progress-percent="88"', outlined_viewer_response.text)
        self.assertIn('data-outline-status="done"', outlined_viewer_response.text)
        self.assertIn('data-outline-status="review"', outlined_viewer_response.text)

        plain_viewer_response = self.client.get(f"/resources/{plain_resource.id}?page=2")
        self.assertEqual(plain_viewer_response.status_code, 200)
        self.assertIn('id="page-progress-panel"', plain_viewer_response.text)
        self.assertIn('data-current-page-status="hard"', plain_viewer_response.text)

    def test_review_queue_filters_and_source_links(self) -> None:
        primary_course_response = self.client.post(
            "/courses",
            data={
                "title": "Review Queue Course",
                "topic": "Memory",
                "description": "Primary course for review queue checks.",
            },
            follow_redirects=False,
        )
        self.assertEqual(primary_course_response.status_code, 303)
        primary_course_id = int(urlparse(primary_course_response.headers["location"]).path.rstrip("/").split("/")[-1])

        secondary_course_response = self.client.post(
            "/courses",
            data={
                "title": "Secondary Review Course",
                "topic": "Practice",
                "description": "Secondary course for filter checks.",
            },
            follow_redirects=False,
        )
        self.assertEqual(secondary_course_response.status_code, 303)
        secondary_course_id = int(urlparse(secondary_course_response.headers["location"]).path.rstrip("/").split("/")[-1])

        for course_id, module_title in (
            (primary_course_id, "Queue Module A"),
            (primary_course_id, "Queue Module B"),
            (secondary_course_id, "Queue Module C"),
        ):
            create_module_response = self.client.post(
                f"/courses/{course_id}/modules",
                data={
                    "title": module_title,
                    "description": f"Module {module_title} for review queue checks.",
                },
                follow_redirects=False,
            )
            self.assertEqual(create_module_response.status_code, 303)

        with SessionLocal() as session:
            primary_module_a = (
                session.query(Module)
                .filter(Module.course_id == primary_course_id, Module.title == "Queue Module A")
                .one()
            )
            primary_module_b = (
                session.query(Module)
                .filter(Module.course_id == primary_course_id, Module.title == "Queue Module B")
                .one()
            )
            secondary_module_c = (
                session.query(Module)
                .filter(Module.course_id == secondary_course_id, Module.title == "Queue Module C")
                .one()
            )

        for module_id, title, with_outline in (
            (primary_module_a.id, "Queue Outline PDF", True),
            (primary_module_a.id, "Queue Page PDF", False),
            (primary_module_b.id, "Queue Module B PDF", False),
            (secondary_module_c.id, "Queue Secondary PDF", False),
        ):
            import_response = self.client.post(
                f"/modules/{module_id}/resources/pdf",
                data={
                    "title": title,
                    "description": f"{title} description.",
                },
                files={
                    "file": (
                        f"{title.lower().replace(' ', '-')}.pdf",
                        _build_pdf_bytes(with_outline=with_outline),
                        "application/pdf",
                    )
                },
                follow_redirects=False,
            )
            self.assertEqual(import_response.status_code, 303)

        with SessionLocal() as session:
            outline_resource = session.query(Resource).filter(Resource.title == "Queue Outline PDF").one()
            page_resource = session.query(Resource).filter(Resource.title == "Queue Page PDF").one()
            module_b_resource = session.query(Resource).filter(Resource.title == "Queue Module B PDF").one()
            secondary_resource = session.query(Resource).filter(Resource.title == "Queue Secondary PDF").one()
            outline_items = (
                session.query(ResourceOutlineItem)
                .filter(ResourceOutlineItem.resource_id == outline_resource.id)
                .order_by(ResourceOutlineItem.id)
                .all()
            )
            root_item = next(item for item in outline_items if item.parent_id is None)
            child_item = next(item for item in outline_items if item.parent_id == root_item.id)

        outline_review_response = self.client.post(
            f"/resources/{outline_resource.id}/outline-items/{child_item.id}/status",
            data={
                "status_value": ProgressStatus.REVIEW.value,
                "return_page": 2,
                "redirect_anchor": f"outline-item-{child_item.id}",
            },
            follow_redirects=False,
        )
        self.assertEqual(outline_review_response.status_code, 303)

        page_hard_response = self.client.post(
            f"/resources/{page_resource.id}/pages/status",
            data={
                "page_number": 2,
                "status_value": ProgressStatus.HARD.value,
                "redirect_anchor": "page-progress-panel",
            },
            follow_redirects=False,
        )
        self.assertEqual(page_hard_response.status_code, 303)

        module_b_review_response = self.client.post(
            f"/resources/{module_b_resource.id}/pages/status",
            data={
                "page_number": 1,
                "status_value": ProgressStatus.REVIEW.value,
                "redirect_anchor": "page-progress-panel",
            },
            follow_redirects=False,
        )
        self.assertEqual(module_b_review_response.status_code, 303)

        secondary_hard_response = self.client.post(
            f"/resources/{secondary_resource.id}/pages/status",
            data={
                "page_number": 1,
                "status_value": ProgressStatus.HARD.value,
                "redirect_anchor": "page-progress-panel",
            },
            follow_redirects=False,
        )
        self.assertEqual(secondary_hard_response.status_code, 303)

        with SessionLocal() as session:
            page_anchor = (
                session.query(Anchor)
                .filter(Anchor.resource_id == page_resource.id, Anchor.page_number == 2)
                .one()
            )
            module_b_anchor = (
                session.query(Anchor)
                .filter(Anchor.resource_id == module_b_resource.id, Anchor.page_number == 1)
                .one()
            )
            secondary_anchor = (
                session.query(Anchor)
                .filter(Anchor.resource_id == secondary_resource.id, Anchor.page_number == 1)
                .one()
            )

        review_page = self.client.get("/review")
        self.assertEqual(review_page.status_code, 200)
        self.assertIn(f'id="review-item-outline-item-{child_item.id}"', review_page.text)
        self.assertIn(f'id="review-item-page-{page_anchor.id}"', review_page.text)
        self.assertIn(f'id="review-item-page-{module_b_anchor.id}"', review_page.text)
        self.assertIn(f'id="review-item-page-{secondary_anchor.id}"', review_page.text)
        self.assertIn(f'/resources/{outline_resource.id}?page=2#pdf-reader', review_page.text)
        self.assertIn(f'/resources/{page_resource.id}?page=2#pdf-reader', review_page.text)
        self.assertIn(f'/resources/{module_b_resource.id}?page=1#pdf-reader', review_page.text)
        self.assertIn(f'/resources/{secondary_resource.id}?page=1#pdf-reader', review_page.text)

        empty_filter_values_page = self.client.get("/review?course_id=&module_id=&resource_id=")
        self.assertEqual(empty_filter_values_page.status_code, 200)
        self.assertIn(f'id="review-item-outline-item-{child_item.id}"', empty_filter_values_page.text)
        self.assertIn(f'id="review-item-page-{page_anchor.id}"', empty_filter_values_page.text)

        course_filtered_page = self.client.get(f"/review?course_id={primary_course_id}")
        self.assertEqual(course_filtered_page.status_code, 200)
        self.assertIn(f'id="review-item-outline-item-{child_item.id}"', course_filtered_page.text)
        self.assertIn(f'id="review-item-page-{page_anchor.id}"', course_filtered_page.text)
        self.assertIn(f'id="review-item-page-{module_b_anchor.id}"', course_filtered_page.text)
        self.assertNotIn(f'id="review-item-page-{secondary_anchor.id}"', course_filtered_page.text)

        module_filtered_page = self.client.get(f"/review?module_id={primary_module_b.id}")
        self.assertEqual(module_filtered_page.status_code, 200)
        self.assertIn(f'id="review-item-page-{module_b_anchor.id}"', module_filtered_page.text)
        self.assertNotIn(f'id="review-item-outline-item-{child_item.id}"', module_filtered_page.text)
        self.assertNotIn(f'id="review-item-page-{page_anchor.id}"', module_filtered_page.text)
        self.assertNotIn(f'id="review-item-page-{secondary_anchor.id}"', module_filtered_page.text)

        resource_filtered_page = self.client.get(f"/review?resource_id={page_resource.id}")
        self.assertEqual(resource_filtered_page.status_code, 200)
        self.assertIn(f'id="review-item-page-{page_anchor.id}"', resource_filtered_page.text)
        self.assertNotIn(f'id="review-item-outline-item-{child_item.id}"', resource_filtered_page.text)
        self.assertNotIn(f'id="review-item-page-{module_b_anchor.id}"', resource_filtered_page.text)
        self.assertNotIn(f'id="review-item-page-{secondary_anchor.id}"', resource_filtered_page.text)

        source_viewer_response = self.client.get(f"/resources/{outline_resource.id}?page=2")
        self.assertEqual(source_viewer_response.status_code, 200)
        self.assertIn('data-initial-page="2"', source_viewer_response.text)
        self.assertIn(f'id="outline-item-{child_item.id}"', source_viewer_response.text)


def _build_pdf_bytes(*, with_outline: bool, outline_titles: list[str] | None = None) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_blank_page(width=200, height=200)

    if with_outline:
        if outline_titles:
            for index, title in enumerate(outline_titles):
                writer.add_outline_item(title, index % 2)
        else:
            root = writer.add_outline_item("Intro", 0)
            writer.add_outline_item("Deep Dive", 1, parent=root)

    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


if __name__ == "__main__":
    unittest.main()
