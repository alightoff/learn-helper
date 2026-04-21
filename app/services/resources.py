from __future__ import annotations

from pathlib import Path
import re
import shutil
import unicodedata
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.enums import OutlineSourceType, ResourceType
from app.db.models import Course, Module, Resource, ResourceOutlineItem
from app.services.pdf_parser import ParsedOutlineItem, PdfParseError, parse_pdf_document

_FILENAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")


class PdfImportError(Exception):
    """Raised when PDF import cannot be completed."""


def import_pdf_resource(
    db: Session,
    *,
    settings: Settings,
    course: Course,
    module: Module,
    upload: UploadFile,
    title: str | None = None,
    description: str | None = None,
) -> Resource:
    original_file_name = _normalize_original_filename(upload.filename)
    storage_relative_path = _build_storage_relative_path(course.slug, module.id, original_file_name)
    storage_absolute_path = _resolve_storage_path(settings, storage_relative_path)
    storage_absolute_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        upload.file.seek(0)
        with storage_absolute_path.open("wb") as destination:
            shutil.copyfileobj(upload.file, destination)

        parsed_document = parse_pdf_document(storage_absolute_path)
        resource = Resource(
            course_id=course.id,
            module_id=module.id,
            title=_resolve_resource_title(title, original_file_name),
            resource_type=ResourceType.PDF,
            file_path=storage_relative_path.as_posix(),
            original_file_name=original_file_name,
            mime_type=upload.content_type or "application/pdf",
            description=_clean_optional_text(description),
            page_count=parsed_document.page_count,
        )
        db.add(resource)
        db.flush()

        _persist_outline_items(
            db,
            resource_id=resource.id,
            outline_items=parsed_document.outline_items,
        )

        db.commit()
        db.refresh(resource)
        return resource
    except PdfParseError as exc:
        db.rollback()
        _remove_file_if_exists(storage_absolute_path)
        raise PdfImportError(str(exc)) from exc
    except Exception:
        db.rollback()
        _remove_file_if_exists(storage_absolute_path)
        raise


def _persist_outline_items(
    db: Session,
    *,
    resource_id: int,
    outline_items: list[ParsedOutlineItem],
    parent_id: int | None = None,
) -> None:
    for position, item in enumerate(outline_items):
        outline_record = ResourceOutlineItem(
            resource_id=resource_id,
            parent_id=parent_id,
            title=item.title[:255],
            position=position,
            page_number=item.page_number,
            source_type=OutlineSourceType.PARSED,
        )
        db.add(outline_record)
        db.flush()
        _persist_outline_items(
            db,
            resource_id=resource_id,
            outline_items=item.children,
            parent_id=outline_record.id,
        )


def _normalize_original_filename(filename: str | None) -> str:
    candidate = (filename or "").replace("\\", "/").split("/")[-1].strip()
    return candidate or "document.pdf"


def _build_storage_relative_path(course_slug: str, module_id: int, original_file_name: str) -> Path:
    sanitized_stem = _sanitize_component(Path(original_file_name).stem, fallback="document")
    unique_name = f"{uuid4().hex}_{sanitized_stem}.pdf"
    return Path("courses") / course_slug / "resources" / f"module-{module_id}" / unique_name


def _resolve_storage_path(settings: Settings, relative_path: Path) -> Path:
    uploads_root = settings.uploads_dir.resolve()
    absolute_path = (settings.uploads_dir / relative_path).resolve()
    if not absolute_path.is_relative_to(uploads_root):
        raise PdfImportError("The computed storage path is outside the uploads directory.")
    return absolute_path


def _resolve_resource_title(provided_title: str | None, original_file_name: str) -> str:
    if provided_title and provided_title.strip():
        return provided_title.strip()[:255]

    fallback_title = Path(original_file_name).stem.strip()
    return (fallback_title or "Untitled PDF")[:255]


def _sanitize_component(value: str, *, fallback: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    sanitized = _FILENAME_RE.sub("-", ascii_value).strip("-.").lower()
    return sanitized or fallback


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = value.strip()
    return normalized or None


def _remove_file_if_exists(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
