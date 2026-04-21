from __future__ import annotations

from enum import Enum as PyEnum

from sqlalchemy import Enum


def enum_type(enum_cls: type[PyEnum]) -> Enum:
    return Enum(
        enum_cls,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
        name=f"{enum_cls.__name__.lower()}_enum",
    )
