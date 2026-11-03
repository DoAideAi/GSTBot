"""Previewed spreadsheet imports; no external AI or automatic commits."""

import json
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_business, get_current_user, require_writer
from app.core.params import RowId
from app.core.rate_limit import RateLimit
from app.core.sanitize import clean_text
from app.models.business import Business
from app.models.mixins import utcnow
from app.models.practice import RegisterImport, RegisterMapping
from app.models.user import User
from app.schemas.practice import RegisterCommit
from app.services import register_import as service

router = APIRouter(prefix="/register-imports", tags=["purchase registers"])


@router.get(
    "/mappings",
    summary="Saved purchase-register column mappings",
    dependencies=[Depends(RateLimit("register_read", "120/minute"))],
)
def mappings(
    db: Session = Depends(get_db), business: Business = Depends(get_current_business)
) -> dict:
    rows = db.scalars(
        select(RegisterMapping)
        .where(RegisterMapping.business_id == business.id, RegisterMapping.deleted_at.is_(None))
        .order_by(RegisterMapping.name)
    ).all()
    return {
        "items": [
            {"id": r.id, "name": r.name, "mapping": r.mapping, "date_format": r.date_format}
            for r in rows
        ],
        "fields": list(service.FIELDS),
        "required": sorted(service.REQUIRED),
    }


@router.post(
    "/preview",
    summary="Preview a purchase register without creating invoices",
    dependencies=[Depends(require_writer), Depends(RateLimit("register_preview", "10/minute"))],
)
def preview(
    file: UploadFile = File(...),
    mapping: str = Form("{}"),
    date_format: Literal["DMY", "MDY", "YMD"] = Form("DMY"),
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
    user: User = Depends(get_current_user),
) -> dict:
    content = file.file.read(service.MAX_BYTES + 1)
    filename = (
        clean_text(
            (file.filename or "register.csv").replace("\\", "/").split("/")[-1], max_length=255
        )
        or "register.csv"
    )
    headers, values = service.read_file(content, filename)
    try:
        selected = json.loads(mapping)
        if not isinstance(selected, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) for k, v in selected.items()
        ):
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(
            422, "Column mapping must be an object of field names and column headings."
        ) from None
    selected = selected or service.suggest(headers)
    rows = service.preview_rows(db, business, headers, values, selected, date_format)
    # Drafts contain only the mapped invoice fields. Expired drafts are removed;
    # committed imports retain their source-row evidence with the invoices.
    db.execute(
        update(RegisterImport)
        .where(
            RegisterImport.business_id == business.id,
            RegisterImport.deleted_at.is_(None),
            RegisterImport.committed_at.is_(None),
            RegisterImport.expires_at < utcnow(),
        )
        .values(deleted_at=utcnow(), rows=[])
    )
    drafts = list(
        db.scalars(
            select(RegisterImport.id)
            .where(
                RegisterImport.business_id == business.id,
                RegisterImport.deleted_at.is_(None),
                RegisterImport.committed_at.is_(None),
            )
            .order_by(RegisterImport.id.desc())
        )
    )
    if len(drafts) >= 10:
        db.execute(
            update(RegisterImport)
            .where(
                RegisterImport.id.in_(drafts[9:]),
                RegisterImport.business_id == business.id,
                RegisterImport.deleted_at.is_(None),
            )
            .values(deleted_at=utcnow(), rows=[])
        )
    batch = RegisterImport(
        business_id=business.id,
        created_by=user.id,
        filename=filename,
        headers=headers,
        mapping={"columns": selected, "date_format": date_format},
        rows=rows,
        expires_at=utcnow() + timedelta(minutes=30),
    )
    db.add(batch)
    db.commit()
    return {
        "id": batch.id,
        "headers": headers,
        "mapping": selected,
        "date_format": date_format,
        "fields": list(service.FIELDS),
        "required": sorted(service.REQUIRED),
        "rows": rows,
        "expires_at": batch.expires_at,
        "ready": sum(not r["errors"] and not r["duplicate"] for r in rows),
        "invalid": sum(bool(r["errors"]) for r in rows),
        "duplicates": sum(not r["errors"] and r["duplicate"] for r in rows),
    }


@router.post(
    "/{import_id}/commit",
    summary="Import validated purchase-register rows atomically",
    dependencies=[Depends(require_writer), Depends(RateLimit("register_commit", "10/minute"))],
)
def commit(
    import_id: RowId,
    payload: RegisterCommit,
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
) -> dict:
    batch = db.scalar(
        select(RegisterImport)
        .where(
            RegisterImport.id == import_id,
            RegisterImport.business_id == business.id,
            RegisterImport.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if batch is None:
        raise HTTPException(404, "Import preview not found. Upload the register again.")
    if batch.committed_at:
        return batch.result
    if service.aware(batch.expires_at) < utcnow():
        raise HTTPException(409, "This preview expired. Preview the file again before importing.")
    try:
        result = service.commit_rows(db, business, batch, payload.skip_invalid)
        name = clean_text(payload.save_mapping_name, max_length=80)
        if name:
            saved = db.scalar(
                select(RegisterMapping).where(
                    RegisterMapping.business_id == business.id,
                    RegisterMapping.deleted_at.is_(None),
                    RegisterMapping.name == name,
                )
            )
            if saved is None:
                saved = RegisterMapping(business_id=business.id, name=name)
                db.add(saved)
            saved.mapping = batch.mapping["columns"]
            saved.date_format = batch.mapping["date_format"]
        batch.result, batch.committed_at = result, utcnow()
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            409,
            "The register changed during import. Preview again; no rows "
            "from this attempt were saved.",
        ) from None
    return result
