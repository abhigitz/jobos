from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func

from app.database import get_db
from app.utils import escape_like
from app.dependencies import get_current_user
from app.models.user import User
from app.models.job import Job
from app.models.company import Company
from app.models.contact import Contact

router = APIRouter(prefix="/search", tags=["search"])


@router.get("")
async def global_search(
    q: str = Query(..., min_length=2),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Search across jobs, companies, and contacts."""
    search_term = f"%{escape_like(q.lower())}%"

    # Search jobs (using role_title as title, is_deleted for soft delete)
    jobs_result = await db.execute(
        select(Job)
        .where(Job.user_id == current_user.id)
        .where(Job.is_deleted.is_(False))
        .where(
            or_(
                func.lower(Job.role_title).like(search_term),
                func.lower(Job.company_name).like(search_term),
            )
        )
        .limit(10)
    )
    jobs = jobs_result.scalars().all()

    # Search companies
    companies_result = await db.execute(
        select(Company)
        .where(Company.user_id == current_user.id)
        .where(func.lower(Company.name).like(search_term))
        .limit(10)
    )
    companies = companies_result.scalars().all()

    # Search contacts (using is_deleted for soft delete)
    contacts_result = await db.execute(
        select(Contact)
        .where(Contact.user_id == current_user.id)
        .where(Contact.is_deleted.is_(False))
        .where(
            or_(
                func.lower(Contact.name).like(search_term),
                func.lower(Contact.company).like(search_term),
            )
        )
        .limit(10)
    )
    contacts = contacts_result.scalars().all()

    return {
        "jobs": [
            {"id": str(j.id), "title": j.role_title, "company_name": j.company_name, "type": "job"}
            for j in jobs
        ],
        "companies": [
            {"id": str(c.id), "name": c.name, "type": "company"} for c in companies
        ],
        "contacts": [
            {"id": str(c.id), "name": c.name, "company": c.company, "type": "contact"}
            for c in contacts
        ],
    }
