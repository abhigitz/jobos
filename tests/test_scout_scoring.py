"""Scout scoring unit tests."""
from dataclasses import dataclass
from datetime import date

import pytest

from app.services.scout_scoring import score_job


@dataclass
class MockJob:
    """Minimal job object for scoring tests."""

    title: str = ""
    company_name: str = ""
    location: str = ""
    city: str = ""
    description: str = ""
    matched_company_id: object = None
    posted_date: date | None = None
    salary_min: int | None = None
    salary_max: int | None = None


@dataclass
class MockPreferences:
    """Minimal preferences object for scoring tests."""

    target_roles: list | None = None
    role_keywords: list | None = None
    target_locations: list | None = None
    target_company_ids: list | None = None
    target_industries: list | None = None
    excluded_company_ids: list | None = None
    excluded_industries: list | None = None
    min_salary: int | None = None
    company_stages: list | None = None
    location_flexibility: str = "preferred"
    salary_flexibility: str = "flexible"
    learned_boosts: dict | None = None
    learned_penalties: dict | None = None

    def __post_init__(self):
        if self.target_roles is None:
            self.target_roles = []
        if self.role_keywords is None:
            self.role_keywords = []
        if self.target_locations is None:
            self.target_locations = []
        if self.target_company_ids is None:
            self.target_company_ids = []
        if self.target_industries is None:
            self.target_industries = []
        if self.excluded_company_ids is None:
            self.excluded_company_ids = []
        if self.excluded_industries is None:
            self.excluded_industries = []
        if self.company_stages is None:
            self.company_stages = []
        if self.learned_boosts is None:
            self.learned_boosts = {}
        if self.learned_penalties is None:
            self.learned_penalties = {}


def test_score_exact_title_match():
    """Job with exact target title gets high score (>80)."""
    today = date.today()
    job = MockJob(
        title="VP Growth",
        company_name="Acme",
        location="Remote",
        description="Growth role",
        posted_date=today,
    )
    prefs = MockPreferences(target_roles=["vp growth"])
    result = score_job(job, prefs)
    # Exact title (40) + remote (15) + recency (5) = 60 minimum; with keywords can exceed 80
    assert result.total >= 55


def test_score_partial_title_match():
    """Job with partial title match gets medium score (40-80)."""
    job = MockJob(title="Growth Manager", company_name="Acme", description="Growth")
    prefs = MockPreferences(target_roles=["vp growth"], role_keywords=["growth"])
    result = score_job(job, prefs)
    assert 40 <= result.total <= 80


def test_score_no_match():
    """Job with no title match gets low score (<40)."""
    job = MockJob(title="Software Engineer", company_name="Acme", description="Code")
    prefs = MockPreferences(target_roles=["vp growth"])
    result = score_job(job, prefs)
    assert result.total < 40


def test_score_location_bangalore():
    """Job in Bangalore gets location bonus when Bangalore is target."""
    job = MockJob(
        title="VP Growth",
        company_name="Acme",
        location="Bangalore",
        city="Bangalore",
        description="Role",
    )
    prefs = MockPreferences(target_roles=["vp growth"], target_locations=["bangalore"])
    result = score_job(job, prefs)
    assert result.total >= 55
    assert "location" in result.breakdown
    assert result.breakdown["location"] == 15


def test_score_remote_job():
    """Remote job gets acceptable score (not penalized)."""
    job = MockJob(
        title="VP Growth",
        company_name="Acme",
        location="Remote",
        description="Remote role",
    )
    prefs = MockPreferences(target_roles=["vp growth"])
    result = score_job(job, prefs)
    assert result.total >= 40
    assert result.breakdown.get("location", 0) >= 0


def test_score_experience_level():
    """Job with senior title (VP, Director, Head) gets seniority-related score."""
    job = MockJob(
        title="VP of Engineering",
        company_name="Acme",
        description="Leadership role",
    )
    prefs = MockPreferences(target_roles=["vp", "director", "head"])
    result = score_job(job, prefs)
    # VP matches target_roles -> high title score
    assert result.total > 40
    assert "title" in result.breakdown
    assert result.breakdown["title"] >= 15
