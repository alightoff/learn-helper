from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.enums import (
    AnchorType,
    AnnotationStatus,
    AnnotationType,
    ContentStatus,
    OutlineSourceType,
    ProgressStatus,
    ResourceType,
    SessionType,
    TimerMode,
)
from app.db.mixins import CreatedAtMixin, PrimaryKeyMixin, TimestampMixin
from app.db.types import enum_type


class Course(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "courses"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    topic: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[ContentStatus] = mapped_column(
        enum_type(ContentStatus),
        nullable=False,
        default=ContentStatus.ACTIVE,
        index=True,
    )
    cover_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    modules: Mapped[list["Module"]] = relationship(
        back_populates="course",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    resources: Mapped[list["Resource"]] = relationship(
        back_populates="course",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    annotations: Mapped[list["Annotation"]] = relationship(
        back_populates="course",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    progress_records: Mapped[list["ProgressRecord"]] = relationship(
        back_populates="course",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    study_sessions: Mapped[list["StudySession"]] = relationship(
        back_populates="course",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="course",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Module(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "modules"
    __table_args__ = (
        CheckConstraint("position >= 0", name="position_non_negative"),
        Index("ix_modules_course_id_position", "course_id", "position"),
    )

    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[ContentStatus] = mapped_column(
        enum_type(ContentStatus),
        nullable=False,
        default=ContentStatus.ACTIVE,
        index=True,
    )

    course: Mapped[Course] = relationship(back_populates="modules")
    resources: Mapped[list["Resource"]] = relationship(
        back_populates="module",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    annotations: Mapped[list["Annotation"]] = relationship(
        back_populates="module",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    progress_records: Mapped[list["ProgressRecord"]] = relationship(
        back_populates="module",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    study_sessions: Mapped[list["StudySession"]] = relationship(
        back_populates="module",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="module",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Resource(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "resources"
    __table_args__ = (
        CheckConstraint("page_count IS NULL OR page_count >= 0", name="page_count_non_negative"),
        CheckConstraint("duration_seconds IS NULL OR duration_seconds >= 0", name="duration_non_negative"),
        Index("ix_resources_module_id_type", "module_id", "resource_type"),
    )

    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_type: Mapped[ResourceType] = mapped_column(
        enum_type(ResourceType),
        nullable=False,
        index=True,
    )
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    original_file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ContentStatus] = mapped_column(
        enum_type(ContentStatus),
        nullable=False,
        default=ContentStatus.ACTIVE,
        index=True,
    )
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    course: Mapped[Course] = relationship(back_populates="resources")
    module: Mapped[Module] = relationship(back_populates="resources")
    outline_items: Mapped[list["ResourceOutlineItem"]] = relationship(
        back_populates="resource",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    anchors: Mapped[list["Anchor"]] = relationship(
        back_populates="resource",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    annotations: Mapped[list["Annotation"]] = relationship(
        back_populates="resource",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    progress_records: Mapped[list["ProgressRecord"]] = relationship(
        back_populates="resource",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    study_sessions: Mapped[list["StudySession"]] = relationship(
        back_populates="resource",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="resource",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ResourceOutlineItem(PrimaryKeyMixin, Base):
    __tablename__ = "resource_outline_items"
    __table_args__ = (
        CheckConstraint("position >= 0", name="position_non_negative"),
        CheckConstraint("page_number IS NULL OR page_number > 0", name="page_number_positive"),
        CheckConstraint(
            "(time_start_seconds IS NULL OR time_start_seconds >= 0) "
            "AND (time_end_seconds IS NULL OR time_end_seconds >= 0)",
            name="time_offsets_non_negative",
        ),
        CheckConstraint(
            "time_start_seconds IS NULL "
            "OR time_end_seconds IS NULL "
            "OR time_end_seconds >= time_start_seconds",
            name="time_range_valid",
        ),
        Index("ix_resource_outline_items_resource_id_parent_id_position", "resource_id", "parent_id", "position"),
    )

    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("resource_outline_items.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_start_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_end_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[ProgressStatus] = mapped_column(
        enum_type(ProgressStatus),
        nullable=False,
        default=ProgressStatus.NOT_STARTED,
        index=True,
    )
    source_type: Mapped[OutlineSourceType] = mapped_column(
        enum_type(OutlineSourceType),
        nullable=False,
        default=OutlineSourceType.MANUAL,
        index=True,
    )

    resource: Mapped[Resource] = relationship(back_populates="outline_items")
    parent: Mapped["ResourceOutlineItem | None"] = relationship(
        back_populates="children",
        remote_side=lambda: ResourceOutlineItem.id,
    )
    children: Mapped[list["ResourceOutlineItem"]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    anchors: Mapped[list["Anchor"]] = relationship(back_populates="outline_item")
    progress_records: Mapped[list["ProgressRecord"]] = relationship(back_populates="outline_item")
    attachments: Mapped[list["Attachment"]] = relationship(back_populates="outline_item")


class Anchor(PrimaryKeyMixin, Base):
    __tablename__ = "anchors"
    __table_args__ = (
        CheckConstraint("page_number IS NULL OR page_number > 0", name="page_number_positive"),
        CheckConstraint(
            "(time_start_seconds IS NULL OR time_start_seconds >= 0) "
            "AND (time_end_seconds IS NULL OR time_end_seconds >= 0)",
            name="time_offsets_non_negative",
        ),
        CheckConstraint(
            "time_start_seconds IS NULL "
            "OR time_end_seconds IS NULL "
            "OR time_end_seconds >= time_start_seconds",
            name="time_range_valid",
        ),
        Index("ix_anchors_resource_id_anchor_type", "resource_id", "anchor_type"),
    )

    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id", ondelete="CASCADE"), nullable=False, index=True)
    anchor_type: Mapped[AnchorType] = mapped_column(
        enum_type(AnchorType),
        nullable=False,
        index=True,
    )
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    selection_data: Mapped[dict[str, object] | list[object] | None] = mapped_column(JSON, nullable=True)
    time_start_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_end_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outline_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("resource_outline_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    resource: Mapped[Resource] = relationship(back_populates="anchors")
    outline_item: Mapped[ResourceOutlineItem | None] = relationship(back_populates="anchors")
    annotations: Mapped[list["Annotation"]] = relationship(back_populates="anchor")
    progress_records: Mapped[list["ProgressRecord"]] = relationship(back_populates="anchor")


class Annotation(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "annotations"
    __table_args__ = (
        Index("ix_annotations_course_id_status", "course_id", "status"),
        Index("ix_annotations_resource_id_annotation_type", "resource_id", "annotation_type"),
    )

    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    module_id: Mapped[int | None] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"), nullable=True, index=True)
    resource_id: Mapped[int | None] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    anchor_id: Mapped[int | None] = mapped_column(ForeignKey("anchors.id", ondelete="SET NULL"), nullable=True, index=True)
    annotation_type: Mapped[AnnotationType] = mapped_column(
        enum_type(AnnotationType),
        nullable=False,
        default=AnnotationType.QUICK_NOTE,
        index=True,
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[AnnotationStatus] = mapped_column(
        enum_type(AnnotationStatus),
        nullable=False,
        default=AnnotationStatus.ACTIVE,
        index=True,
    )
    priority: Mapped[int | None] = mapped_column(Integer, nullable=True)

    course: Mapped[Course] = relationship(back_populates="annotations")
    module: Mapped[Module | None] = relationship(back_populates="annotations")
    resource: Mapped[Resource | None] = relationship(back_populates="annotations")
    anchor: Mapped[Anchor | None] = relationship(back_populates="annotations")


class ProgressRecord(PrimaryKeyMixin, Base):
    __tablename__ = "progress_records"
    __table_args__ = (
        CheckConstraint(
            "course_id IS NOT NULL "
            "OR module_id IS NOT NULL "
            "OR resource_id IS NOT NULL "
            "OR outline_item_id IS NOT NULL "
            "OR anchor_id IS NOT NULL",
            name="has_target",
        ),
        CheckConstraint(
            "progress_percent IS NULL OR (progress_percent >= 0 AND progress_percent <= 100)",
            name="progress_percent_range",
        ),
        Index("ix_progress_records_status_last_interacted_at", "status", "last_interacted_at"),
    )

    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=True, index=True)
    module_id: Mapped[int | None] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"), nullable=True, index=True)
    resource_id: Mapped[int | None] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    outline_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("resource_outline_items.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    anchor_id: Mapped[int | None] = mapped_column(ForeignKey("anchors.id", ondelete="SET NULL"), nullable=True, index=True)
    status: Mapped[ProgressStatus] = mapped_column(
        enum_type(ProgressStatus),
        nullable=False,
        default=ProgressStatus.NOT_STARTED,
        index=True,
    )
    progress_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_interacted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    course: Mapped[Course | None] = relationship(back_populates="progress_records")
    module: Mapped[Module | None] = relationship(back_populates="progress_records")
    resource: Mapped[Resource | None] = relationship(back_populates="progress_records")
    outline_item: Mapped[ResourceOutlineItem | None] = relationship(back_populates="progress_records")
    anchor: Mapped[Anchor | None] = relationship(back_populates="progress_records")


class StudySession(PrimaryKeyMixin, Base):
    __tablename__ = "study_sessions"
    __table_args__ = (
        CheckConstraint("duration_seconds IS NULL OR duration_seconds >= 0", name="duration_non_negative"),
        CheckConstraint(
            "work_interval_seconds IS NULL OR work_interval_seconds > 0",
            name="work_interval_positive",
        ),
        CheckConstraint(
            "break_interval_seconds IS NULL OR break_interval_seconds >= 0",
            name="break_interval_non_negative",
        ),
        CheckConstraint("cycles_completed IS NULL OR cycles_completed >= 0", name="cycles_non_negative"),
        Index("ix_study_sessions_started_at_session_type", "started_at", "session_type"),
    )

    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=True, index=True)
    module_id: Mapped[int | None] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"), nullable=True, index=True)
    resource_id: Mapped[int | None] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    session_type: Mapped[SessionType] = mapped_column(
        enum_type(SessionType),
        nullable=False,
        index=True,
    )
    timer_mode: Mapped[TimerMode] = mapped_column(
        enum_type(TimerMode),
        nullable=False,
        default=TimerMode.FREE,
        index=True,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    work_interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    break_interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cycles_completed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    course: Mapped[Course | None] = relationship(back_populates="study_sessions")
    module: Mapped[Module | None] = relationship(back_populates="study_sessions")
    resource: Mapped[Resource | None] = relationship(back_populates="study_sessions")


class Attachment(PrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "attachments"
    __table_args__ = (
        CheckConstraint(
            "course_id IS NOT NULL "
            "OR module_id IS NOT NULL "
            "OR resource_id IS NOT NULL "
            "OR outline_item_id IS NOT NULL",
            name="has_owner",
        ),
    )

    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=True, index=True)
    module_id: Mapped[int | None] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"), nullable=True, index=True)
    resource_id: Mapped[int | None] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    outline_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("resource_outline_items.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)

    course: Mapped[Course | None] = relationship(back_populates="attachments")
    module: Mapped[Module | None] = relationship(back_populates="attachments")
    resource: Mapped[Resource | None] = relationship(back_populates="attachments")
    outline_item: Mapped[ResourceOutlineItem | None] = relationship(back_populates="attachments")


__all__ = [
    "Anchor",
    "Annotation",
    "Attachment",
    "Base",
    "Course",
    "Module",
    "ProgressRecord",
    "Resource",
    "ResourceOutlineItem",
    "StudySession",
]
