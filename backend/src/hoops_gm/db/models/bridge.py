"""Raw, authenticated captures received from the Fantrax browser bridge.

The bridge deliberately stores observations, not an interpretation of them.
Keeping both the exact envelope and the response body fields makes a capture
replayable and lets a future parser be corrected without recapturing a game.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from hoops_gm.db.base import Base, IntPk, TimestampMixin, UTCDateTime


class BridgePayload(IntPk, TimestampMixin, Base):
    """One ``hoops-gm.bridge-payload.v1`` envelope, unchanged at the boundary."""

    __tablename__ = "bridge_payloads"
    __table_args__ = (
        Index("ix_bridge_payloads_captured_at", "captured_at"),
        Index("ix_bridge_payloads_dedupe_key", "dedupe_key"),
    )

    schema_name: Mapped[str] = mapped_column("schema", Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    request_method: Mapped[str] = mapped_column(Text, nullable=False)
    request_url: Mapped[str] = mapped_column(Text, nullable=False)
    response_status: Mapped[int | None] = mapped_column(nullable=True)
    response_ok: Mapped[bool] = mapped_column(nullable=False)
    response_content_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_raw: Mapped[str] = mapped_column(Text, nullable=False)
    body_json: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    body_parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    dedupe_key: Mapped[str] = mapped_column(Text, nullable=False)
    #: Exact UTF-8 request body, retained for diagnosis and future re-parsing.
    raw_payload: Mapped[str] = mapped_column(Text, nullable=False)
    replay_count: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    last_replayed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_replay_error: Mapped[str | None] = mapped_column(Text, nullable=True)
