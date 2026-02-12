"""Resume file upload, download, and management."""
import io
import logging
from pathlib import Path
from uuid import UUID

import fitz
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.resume import ResumeFile
from app.services.activity_log import log_activity

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
ALLOWED_MIME = "application/pdf"
_DEBUG_LOG = Path(__file__).resolve().parents[2] / "debug_resume.log"


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
    try:
        with open(_DEBUG_LOG, "a") as _log:
            import json
            _log.write(json.dumps({"id":"log_entry","timestamp":__import__("time").time()*1000,"location":"resume.py:upload_resume","message":"upload_resume entry","data":{"user_id":str(current_user.id),"filename":file.filename},"hypothesisId":"H5"})+"\n")
    except Exception:
        pass
    # #endregion
    if file.content_type != ALLOWED_MIME:
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File size exceeds 5MB limit")

    # #region agent log
    try:
        extracted_text = _extract_text_from_pdf(content)
        with open(_DEBUG_LOG, "a") as _log:
            import json
            _log.write(json.dumps({"id":"log_fitz","timestamp":__import__("time").time()*1000,"location":"resume.py:after_fitz","message":"PDF extraction done","data":{"text_len":len(extracted_text) if extracted_text else 0},"hypothesisId":"H2"})+"\n")
    except Exception as e:
        try:
            with open(_DEBUG_LOG, "a") as _log:
                import json, traceback
                _log.write(json.dumps({"id":"log_fitz_err","timestamp":__import__("time").time()*1000,"location":"resume.py:fitz","message":"fitz failed","data":{"error":str(e),"tb":traceback.format_exc()},"hypothesisId":"H2"})+"\n")
        except Exception:
            pass
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
        await db.commit()

        return {
            "id": str(resume.id),
            "filename": resume.filename,
            "file_size": resume.file_size,
            "version": resume.version,
            "is_primary": resume.is_primary,
            "created_at": resume.created_at.isoformat(),
        }
    except ProgrammingError as e:
        err_msg = str(e.orig) if hasattr(e, "orig") and e.orig else str(e)
        if "does not exist" in err_msg or "resume_files" in err_msg:
            raise HTTPException(
                status_code=503,
                detail="resume_files table not found. Run: alembic upgrade head",
            ) from e
        raise
    except Exception as e:
        # #region agent log
        try:
            with open(_DEBUG_LOG, "a") as _log:
                import json, traceback
                _log.write(json.dumps({"id":"log_db_err","timestamp":__import__("time").time()*1000,"location":"resume.py:db_exc","message":"DB/upload error","data":{"error":str(e),"tb":traceback.format_exc()},"hypothesisId":"H1,H3,H4"})+"\n")
        except Exception:
            pass
        # #endregion
        raise


@router.get("")
async def list_resumes(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """List all resume versions for the current user."""
    rows = (
        await db.execute(
            select(ResumeFile)
            .where(ResumeFile.user_id == current_user.id)
            .order_by(ResumeFile.version.desc())
        )
    ).scalars().all()
    return [
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
    await db.commit()

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
    await db.commit()

    return {"status": "deleted"}
