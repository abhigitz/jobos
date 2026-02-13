"""Resume file upload, download, and management."""
import io
import logging
import os
import tempfile
from pathlib import Path
from uuid import UUID

import fitz
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.exc import ProgrammingError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.exceptions import AIServiceError
from app.dependencies import get_current_user
from app.models.resume import ResumeFile
from app.services.activity_log import log_activity

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
ALLOWED_MIME = "application/pdf"
_DEBUG_LOG = Path(tempfile.gettempdir()) / "jobos_resume_debug.log"
_DBG = Path(tempfile.gettempdir()) / "jobos_resume_debug.log"


def _dbg(msg: str, data: dict, hypothesis_id: str) -> None:
    if os.getenv("JOBOS_DEBUG", "").lower() != "true":
        return
    try:
        import json
        import time

        with open(_DBG, "a") as f:
            f.write(
                json.dumps(
                    {
                        "id": msg,
                        "timestamp": time.time() * 1000,
                        "location": "resume.py",
                        "message": msg,
                        "data": data,
                        "hypothesisId": hypothesis_id,
                    }
                )
                + "\n"
            )
    except Exception as e:
        logger.debug(f"Resume debug helper failed: {e}")
    logger.info("[DEBUG] %s hypothesis=%s data=%s", msg, hypothesis_id, data)


def _extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes using PyMuPDF (fitz)."""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        doc.close()
        return "\n".join(text_parts).strip()
    except Exception as e:
        logger.warning(f"PDF text extraction failed: {e}")
        return ""


@router.post("/upload")
async def upload_resume(
    file: UploadFile | None = File(None),
    resume: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Upload PDF resume. Extracts text, auto-increments version, sets as primary."""
    upload = file or resume
    if upload is None:
        raise HTTPException(status_code=422, detail="Missing file. Send form field 'file' or 'resume' with PDF.")
    file = upload
    # #region agent log
    _dbg("upload_entry", {"user_id": str(current_user.id), "filename": file.filename}, "H5")
    # #endregion
    if file.content_type != ALLOWED_MIME:
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File size exceeds 5MB limit")

    # #region agent log
    try:
        extracted_text = _extract_text_from_pdf(content)
        _dbg("fitz_ok", {"text_len": len(extracted_text) if extracted_text else 0}, "H2")
    except Exception as e:
        import traceback
        _dbg("fitz_err", {"error": str(e)[:200]}, "H2")
        raise
    # #endregion

    # Get next version number
    try:
        max_version = (
            await db.execute(
                select(func.coalesce(func.max(ResumeFile.version), 0)).where(
                    ResumeFile.user_id == current_user.id
                )
            )
        ).scalar() or 0
        next_version = max_version + 1

        # Unset primary on all user's resumes
        existing = (
            await db.execute(select(ResumeFile).where(ResumeFile.user_id == current_user.id))
        ).scalars().all()
        for r in existing:
            r.is_primary = False

        resume = ResumeFile(
            user_id=current_user.id,
            filename=file.filename or "resume.pdf",
            file_content=content,
            file_size=len(content),
            mime_type=ALLOWED_MIME,
            version=next_version,
            is_primary=True,
            extracted_text=extracted_text or None,
        )
        db.add(resume)
        await db.commit()
        await db.refresh(resume)

        await log_activity(
            db, current_user.id, "resume_uploaded",
            f"Uploaded resume v{next_version}: {resume.filename}",
        )

        return {
            "id": str(resume.id),
            "filename": resume.filename,
            "file_size": resume.file_size,
            "version": resume.version,
            "is_primary": resume.is_primary,
            "created_at": resume.created_at.isoformat(),
        }
    except HTTPException:
        raise
    except ProgrammingError as e:
        err_msg = str(e.orig) if hasattr(e, "orig") and e.orig else str(e)
        # #region agent log
        _dbg("H1_prog_err", {"err_msg": err_msg[:200], "has_resume_files": "resume_files" in err_msg, "has_does_not_exist": "does not exist" in err_msg}, "H1")
        # #endregion
        if "does not exist" in err_msg or "resume_files" in err_msg:
            raise HTTPException(
                status_code=503,
                detail="resume_files table not found. Run: alembic upgrade head",
            ) from e
        raise
    except (SQLAlchemyError, AIServiceError) as e:
        logger.error("Resume upload failed: %s", e)
        raise
    except Exception as e:
        # #region agent log
        import traceback
        _dbg("db_upload_err", {"error": str(e)[:200], "type": type(e).__name__}, "H1,H3,H4")
        # #endregion
        logger.exception("Unexpected error during resume upload: %s", e)
        raise


@router.get("")
@router.get("/")
async def list_resumes(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """List all resume versions for the current user."""
    _dbg("list_resumes_entry", {"user_id": str(current_user.id)}, "LIST")
    try:
        rows = (
            await db.execute(
                select(ResumeFile)
                .where(ResumeFile.user_id == current_user.id)
                .order_by(ResumeFile.version.desc())
            )
        ).scalars().all()
        out = [
            {
                "id": str(r.id),
                "filename": r.filename,
                "file_size": r.file_size,
                "version": r.version,
                "is_primary": r.is_primary,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
        _dbg("list_resumes_ok", {"count": len(out)}, "LIST")
        return out
    except HTTPException:
        raise
    except ProgrammingError as e:
        err_msg = str(e.orig) if hasattr(e, "orig") and e.orig else str(e)
        if "does not exist" in err_msg or "resume_files" in err_msg:
            _dbg("list_resumes_table_missing", {"err": err_msg[:100]}, "LIST")
            return []
        raise
    except (SQLAlchemyError, AIServiceError) as e:
        logger.error("List resumes failed: %s", e)
        raise
    except Exception as e:
        _dbg("list_resumes_err", {"error": str(e)[:200], "type": type(e).__name__}, "LIST")
        logger.exception("Unexpected error listing resumes: %s", e)
        raise


@router.get("/{resume_id}/download")
async def download_resume(
    resume_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Download PDF file."""
    resume = await db.get(ResumeFile, resume_id)
    if resume is None or resume.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Resume not found")
    return StreamingResponse(
        io.BytesIO(resume.file_content),
        media_type=resume.mime_type,
        headers={"Content-Disposition": f'attachment; filename="{resume.filename}"'},
    )


@router.get("/{resume_id}/text")
async def get_resume_text(
    resume_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Get extracted text from resume."""
    resume = await db.get(ResumeFile, resume_id)
    if resume is None or resume.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Resume not found")
    return {"text": resume.extracted_text or ""}


@router.patch("/{resume_id}/primary")
async def set_primary_resume(
    resume_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Set this resume as the primary one."""
    resume = await db.get(ResumeFile, resume_id)
    if resume is None or resume.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Resume not found")

    # Unset primary on all
    existing = (
        await db.execute(select(ResumeFile).where(ResumeFile.user_id == current_user.id))
    ).scalars().all()
    for r in existing:
        r.is_primary = False
    resume.is_primary = True
    await db.commit()
    await db.refresh(resume)

    await log_activity(
        db, current_user.id, "resume_primary_set",
        f"Set resume v{resume.version} as primary",
    )

    return {"id": str(resume.id), "is_primary": True}


@router.delete("/{resume_id}")
async def delete_resume(
    resume_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Delete a resume version."""
    resume = await db.get(ResumeFile, resume_id)
    if resume is None or resume.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Resume not found")

    await db.delete(resume)
    await db.commit()

    await log_activity(
        db, current_user.id, "resume_deleted",
        f"Deleted resume v{resume.version}: {resume.filename}",
    )

    return {"status": "deleted"}
