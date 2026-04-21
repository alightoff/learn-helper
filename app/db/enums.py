from __future__ import annotations

from enum import Enum


class ContentStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class ProgressStatus(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    REVIEW = "review"
    HARD = "hard"


class ResourceType(str, Enum):
    PDF = "pdf"
    VIDEO_LOCAL = "video_local"
    FILE_ATTACHMENT = "file_attachment"
    LINK_PLACEHOLDER = "link_placeholder"


class OutlineSourceType(str, Enum):
    PARSED = "parsed"
    MANUAL = "manual"


class AnchorType(str, Enum):
    PDF_PAGE = "pdf_page"
    PDF_TEXT = "pdf_text"
    VIDEO_TIMESTAMP = "video_timestamp"
    VIDEO_RANGE = "video_range"
    OUTLINE_ITEM = "outline_item"


class AnnotationType(str, Enum):
    QUICK_NOTE = "quick_note"
    BOOKMARK = "bookmark"
    COMMENT = "comment"
    QUESTION = "question"
    SUMMARY = "summary"
    REVIEW_ITEM = "review_item"


class AnnotationStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class SessionType(str, Enum):
    READING = "reading"
    VIDEO = "video"
    REVIEW = "review"
    PRACTICE = "practice"
    NOTE_TAKING = "note_taking"


class TimerMode(str, Enum):
    FREE = "free"
    POMODORO = "pomodoro"
