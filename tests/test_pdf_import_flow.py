from __future__ import annotations

import io
import os
from pathlib import Path
import shutil
import unittest
from urllib.parse import urlparse

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pypdf import PdfWriter

BASE_DIR = Path(__file__).resolve().parents[1]
RUNTIME_DIR = BASE_DIR / "data" / "test-runtime"

if RUNTIME_DIR.exists():
    shutil.rmtree(RUNTIME_DIR, ignore_errors=True)

os.environ["LEARN_HELPER_DATA_DIR"] = str(RUNTIME_DIR)
os.environ["LEARN_HELPER_DATABASE_URL"] = f"sqlite:///{(RUNTIME_DIR / 'app.db').as_posix()}"

from app.config import get_settings

get_settings.cache_clear()

from app.db.models import Module, Resource, ResourceOutlineItem
from app.db.session import SessionLocal, engine
from app.main import create_app


class PdfImportFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        alembic_config = Config(str(BASE_DIR / "alembic.ini"))
        command.upgrade(alembic_config, "head")
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
