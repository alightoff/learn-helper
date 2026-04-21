from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader


class PdfParseError(Exception):
    """Raised when a file cannot be parsed as a PDF document."""


@dataclass(slots=True)
class ParsedOutlineItem:
    title: str
    page_number: int | None = None
    children: list["ParsedOutlineItem"] = field(default_factory=list)


@dataclass(slots=True)
class ParsedPdfDocument:
    page_count: int
    outline_items: list[ParsedOutlineItem] = field(default_factory=list)


def parse_pdf_document(file_path: Path) -> ParsedPdfDocument:
    try:
        reader = PdfReader(str(file_path))
        page_count = len(reader.pages)
    except Exception as exc:  # pragma: no cover - exercised through service-level validation.
        raise PdfParseError("The uploaded file could not be read as a valid PDF.") from exc

    outline_items: list[ParsedOutlineItem] = []
    try:
        outline_items = _parse_outline_nodes(reader, reader.outline)
    except Exception:
        outline_items = []

    return ParsedPdfDocument(page_count=page_count, outline_items=outline_items)


def _parse_outline_nodes(reader: PdfReader, nodes: object) -> list[ParsedOutlineItem]:
    if not isinstance(nodes, list):
        return []

    parsed_items: list[ParsedOutlineItem] = []
    last_item: ParsedOutlineItem | None = None

    for node in nodes:
        if isinstance(node, list):
            child_items = _parse_outline_nodes(reader, node)
            if last_item is not None:
                last_item.children.extend(child_items)
            else:
                parsed_items.extend(child_items)
            continue

        parsed_item = _parse_outline_node(reader, node)
        if parsed_item is None:
            last_item = None
            continue

        parsed_items.append(parsed_item)
        last_item = parsed_item

    return parsed_items


def _parse_outline_node(reader: PdfReader, node: object) -> ParsedOutlineItem | None:
    title = _extract_title(node)
    if not title:
        return None

    page_number: int | None = None
    try:
        page_number = reader.get_destination_page_number(node) + 1
    except Exception:
        page_number = None

    return ParsedOutlineItem(title=title[:255], page_number=page_number)


def _extract_title(node: object) -> str | None:
    if hasattr(node, "title"):
        value = getattr(node, "title")
        if isinstance(value, str):
            normalized = value.strip()
            if normalized:
                return normalized

    if isinstance(node, dict):
        value = node.get("/Title") or node.get("title")
        if isinstance(value, str):
            normalized = value.strip()
            if normalized:
                return normalized

    normalized = str(node).strip()
    return normalized or None
