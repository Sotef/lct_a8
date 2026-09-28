# -*- coding: utf-8 -*-
"""Вложения заявок (фото с объекта) — MOBILE_PLAN §4.5, §7.

Файлы хранятся вне БД (``config.ATTACH_DIR``), отдаются RBAC-эндпоинтом
``GET /maintenance/attachments/{id}`` с проверкой скоупа объекта заявки.
Принимаются только изображения (jpeg/png/webp) с проверкой сигнатуры.
"""
from __future__ import annotations

import hashlib
import logging
import pathlib

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import config
from .. import models_db as dbm

log = logging.getLogger("attachments")

MAX_BYTES = max(1, config.ATTACH_MAX_MB) * 1024 * 1024
ALLOWED = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


def _sniff_mime(data: bytes) -> str | None:
    """Определяет тип по «magic bytes» (не доверяем клиентскому Content-Type)."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _safe_name(name: str | None) -> str:
    base = (name or "photo.jpg").replace("\\", "/").split("/")[-1]
    return base[:200] or "photo.jpg"


def save(db: Session, ticket: dbm.MaintenanceTask, user_id: int | None,
         filename: str | None, data: bytes) -> dbm.Attachment:
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="пустой файл")
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413,
                            detail=f"файл больше {config.ATTACH_MAX_MB} МБ")
    mime = _sniff_mime(data)
    if mime is None:
        raise HTTPException(status_code=415,
                            detail="допустимы только изображения JPEG/PNG/WEBP")
    sha = hashlib.sha256(data).hexdigest()
    ext = ALLOWED[mime]
    folder = pathlib.Path(config.ATTACH_DIR) / str(ticket.id)
    folder.mkdir(parents=True, exist_ok=True)
    fp = folder / f"{sha[:20]}{ext}"
    if not fp.exists():
        fp.write_bytes(data)
    row = dbm.Attachment(ticket_id=ticket.id, filename=_safe_name(filename),
                         mime=mime, size=len(data), sha256=sha,
                         stored_path=str(fp), uploaded_by=user_id)
    db.add(row)
    db.commit()
    db.refresh(row)
    log.info("attachment saved ticket=%s id=%s size=%s", ticket.id, row.id, len(data))
    return row


def out(a: dbm.Attachment) -> dict:
    return {"id": a.id, "ticket_id": a.ticket_id, "filename": a.filename,
            "mime": a.mime, "size": a.size, "sha256": a.sha256,
            "url": f"/api/v1/maintenance/attachments/{a.id}",
            "uploaded_by": a.uploaded_by,
            "created_at": a.created_at.isoformat() if a.created_at else None}


def list_for(db: Session, ticket_id: int) -> list[dict]:
    rows = (db.query(dbm.Attachment)
            .filter(dbm.Attachment.ticket_id == ticket_id)
            .order_by(dbm.Attachment.id.desc()).all())
    return [out(a) for a in rows]


def get(db: Session, attach_id: int) -> dbm.Attachment:
    a = db.get(dbm.Attachment, attach_id)
    if a is None:
        raise HTTPException(status_code=404, detail="вложение не найдено")
    return a
