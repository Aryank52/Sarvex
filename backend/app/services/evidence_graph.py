"""Scientific evidence graph helpers."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import EvidenceEdge


def record_edge(
    session: Session,
    *,
    source_type: str,
    source_id: str,
    target_type: str,
    target_id: str,
    edge_type: str,
    properties: dict[str, Any] | None = None,
) -> None:
    try:
        session.add(
            EvidenceEdge(
                source_type=source_type,
                source_id=source_id,
                target_type=target_type,
                target_id=target_id,
                edge_type=edge_type,
                properties=properties or {},
            )
        )
        session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()
