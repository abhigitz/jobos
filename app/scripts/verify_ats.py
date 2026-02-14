"""
ATS verification script — tests all 18 company job board integrations
(Greenhouse and Lever).
"""

import asyncio
import json
import logging
from datetime import datetime

import httpx

# Greenhouse: company display name -> board token
GREENHOUSE_COMPANIES: dict[str, str] = {
    "PhonePe": "phonepe",
    "Razorpay": "razorpay",
    "Flipkart": "flipkart",
    "Myntra": "myntra",
    "Groww": "groww82",
    "Zerodha": "zerodha",
    "Cult.fit": "cultfit",
    "Urban Company": "urbancompany",
    "Lenskart": "lenskart",
    "Nykaa": "nykaa",
}

# Lever: company display name -> company slug
LEVER_COMPANIES: dict[str, str] = {
    "CRED": "cred",
    "Meesho": "meesho",
    "Zepto": "zepto",
    "Jupiter": "jupiter-money",
    "Slice": "sliceit",
    "Khatabook": "khatabook",
    "Unacademy": "unacademy",
    "ShareChat": "sharechat",
}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def fetch_greenhouse_jobs(
    client: httpx.AsyncClient, company: str, board_token: str
) -> dict:
    """Fetch jobs from Greenhouse board. Returns verification result dict."""
    url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs"
    try:
        response = await client.get(url, timeout=10.0)
        if response.status_code == 200:
            data = response.json()
            jobs = data.get("jobs", []) if isinstance(data, dict) else []
            sample_title = jobs[0].get("title") if jobs else None
            return {
                "company": company,
                "ats": "Greenhouse",
                "status": response.status_code,
                "job_count": len(jobs),
                "sample_title": sample_title,
                "error": None,
            }
        else:
            return {
                "company": company,
                "ats": "Greenhouse",
                "status": response.status_code,
                "job_count": 0,
                "sample_title": None,
                "error": f"HTTP {response.status_code}",
            }
    except httpx.TimeoutException as e:
        return {
            "company": company,
            "ats": "Greenhouse",
            "status": 0,
            "job_count": 0,
            "sample_title": None,
            "error": f"Timeout: {e}",
        }
    except httpx.ConnectError as e:
        return {
            "company": company,
            "ats": "Greenhouse",
            "status": 0,
            "job_count": 0,
            "sample_title": None,
            "error": f"Connection error: {e}",
        }
    except json.JSONDecodeError as e:
        return {
            "company": company,
            "ats": "Greenhouse",
            "status": getattr(response, "status_code", 0),
            "job_count": 0,
            "sample_title": None,
            "error": f"JSON decode error: {e}",
        }
    except Exception as e:
        return {
            "company": company,
            "ats": "Greenhouse",
            "status": 0,
            "job_count": 0,
            "sample_title": None,
            "error": str(e),
        }


async def fetch_lever_jobs(
    client: httpx.AsyncClient, company: str, slug: str
) -> dict:
    """Fetch jobs from Lever. Returns verification result dict."""
    url = f"https://api.lever.co/v0/postings/{slug}"
    try:
        response = await client.get(url, timeout=10.0)
        if response.status_code == 200:
            data = response.json()
            jobs = data if isinstance(data, list) else []
            sample_title = None
            if jobs and isinstance(jobs[0], dict):
                sample_title = jobs[0].get("text") or jobs[0].get("title")
            return {
                "company": company,
                "ats": "Lever",
                "status": response.status_code,
                "job_count": len(jobs),
                "sample_title": sample_title,
                "error": None,
            }
        else:
            return {
                "company": company,
                "ats": "Lever",
                "status": response.status_code,
                "job_count": 0,
                "sample_title": None,
                "error": f"HTTP {response.status_code}",
            }
    except httpx.TimeoutException as e:
        return {
            "company": company,
            "ats": "Lever",
            "status": 0,
            "job_count": 0,
            "sample_title": None,
            "error": f"Timeout: {e}",
        }
    except httpx.ConnectError as e:
        return {
            "company": company,
            "ats": "Lever",
            "status": 0,
            "job_count": 0,
            "sample_title": None,
            "error": f"Connection error: {e}",
        }
    except json.JSONDecodeError as e:
        return {
            "company": company,
            "ats": "Lever",
            "status": getattr(response, "status_code", 0),
            "job_count": 0,
            "sample_title": None,
            "error": f"JSON decode error: {e}",
        }
    except Exception as e:
        return {
            "company": company,
            "ats": "Lever",
            "status": 0,
            "job_count": 0,
            "sample_title": None,
            "error": str(e),
        }


def _truncate(s: str | None, max_len: int = 28) -> str:
    """Truncate string for table display."""
    if s is None:
        return ""
    s = str(s).strip()
    return (s[: max_len - 3] + "...") if len(s) > max_len else s


async def verify_all_ats() -> None:
    """Verify all 18 ATS integrations concurrently and print results."""
    tasks = []

    async with httpx.AsyncClient() as client:
        for company, board_token in GREENHOUSE_COMPANIES.items():
            tasks.append(fetch_greenhouse_jobs(client, company, board_token))
        for company, slug in LEVER_COMPANIES.items():
            tasks.append(fetch_lever_jobs(client, company, slug))

        results = await asyncio.gather(*tasks)

    # Table dimensions
    col_company = 19
    col_ats = 10
    col_status = 6
    col_jobs = 5
    col_sample = 28

    def pad(s: str, w: int) -> str:
        return s[:w].ljust(w)

    # Header
    print()
    print("╔══════════════════════════════════════════════════════════════════════════════╗")
    print("║                        ATS VERIFICATION RESULTS                               ║")
    print("╠════════════════════════╦════════════╦════════╦═══════╦════════════════════════════╣")
    print(
        "║ "
        + pad("Company", col_company)
        + " ║ "
        + pad("ATS", col_ats)
        + " ║ "
        + pad("Status", col_status)
        + " ║ "
        + pad("Jobs", col_jobs)
        + " ║ "
        + pad("Sample Title", col_sample)
        + " ║"
    )
    print("╠════════════════════════╬════════════╬════════╬═══════╬════════════════════════════╣")

    passed = 0
    failed = 0
    total_jobs = 0
    errors: list[str] = []

    for r in results:
        status_str = str(r["status"]) if r["status"] else "ERR"
        sample = _truncate(r["sample_title"], col_sample)
        if r["error"]:
            sample = _truncate(r["error"], col_sample) if not sample else sample
            errors.append(f"{r['company']} ({r['ats']}): {r['error']}")

        if r["status"] == 200:
            passed += 1
        else:
            failed += 1
        total_jobs += r["job_count"]

        print(
            "║ "
            + pad(r["company"], col_company)
            + " ║ "
            + pad(r["ats"], col_ats)
            + " ║ "
            + pad(status_str, col_status)
            + " ║ "
            + pad(str(r["job_count"]), col_jobs)
            + " ║ "
            + pad(sample, col_sample)
            + " ║"
        )

    print("╚════════════════════════╩════════════╩════════╩═══════╩════════════════════════════╝")
    print()
    print(f"Summary: {passed}/18 passed (HTTP 200), {failed} failed")
    print(f"Total jobs found: {total_jobs}")
    print()

    if errors:
        print("Errors:")
        for err in errors:
            print(f"  - {err}")


if __name__ == "__main__":
    asyncio.run(verify_all_ats())
