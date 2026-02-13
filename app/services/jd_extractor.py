"""Service to extract job description text from URLs."""
import json
import logging
import re
from typing import Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


async def extract_jd_from_url(url: str) -> str | dict:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
    except httpx.TimeoutException:
        raise ValueError("Request timed out. Please paste the JD text manually.")
    except httpx.HTTPStatusError as e:
        raise ValueError(f"Could not fetch URL (HTTP {e.response.status_code}). Please paste the JD text manually.")
    except Exception as e:
        logger.warning(f"JD extraction failed for URL: {e}")
        return {"error": str(e), "extracted": False}

    soup = BeautifulSoup(resp.text, "html.parser")

    # 1. Try JSON-LD (Schema.org JobPosting) — most reliable
    jd_text = _extract_from_json_ld(soup)
    if jd_text and len(jd_text) > 100:
        return _clean_text(jd_text)

    # 2. Site-specific selectors
    domain = urlparse(url).netloc.lower()
    jd_text = _extract_by_domain(soup, domain)
    if jd_text and len(jd_text) > 100:
        return _clean_text(jd_text)

    # 3. Generic selectors for common ATS systems
    jd_text = _extract_generic(soup)
    if jd_text and len(jd_text) > 100:
        return _clean_text(jd_text)

    # 4. Fallback: main content area
    for selector in ["main", "article", "[role='main']", ".content", "#content"]:
        el = soup.select_one(selector)
        if el:
            text = el.get_text(separator="\n", strip=True)
            if len(text) > 200:
                return _clean_text(text)

    # Last resort: body text
    if soup.body:
        return _clean_text(soup.body.get_text(separator="\n", strip=True)[:15000])

    raise ValueError("Could not extract job description from URL. Please paste the JD text manually.")


def _extract_from_json_ld(soup: BeautifulSoup) -> Optional[str]:
    """Extract JD from JSON-LD Schema.org JobPosting."""
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, dict):
                if data.get("@type") == "JobPosting":
                    return data.get("description", "")
                if "@graph" in data:
                    for item in data["@graph"]:
                        if isinstance(item, dict) and item.get("@type") == "JobPosting":
                            return item.get("description", "")
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("@type") == "JobPosting":
                        return item.get("description", "")
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def _extract_by_domain(soup: BeautifulSoup, domain: str) -> Optional[str]:
    """Site-specific extraction logic."""
    selectors = {
        "indeed.com": ["#jobDescriptionText", ".jobsearch-jobDescriptionText"],
        "naukri.com": [".job-desc", ".jd-container", "[class*='job-desc']"],
        "linkedin.com": [".description__text", ".show-more-less-html__markup"],
        "greenhouse.io": ["#content", ".job-description"],
        "lever.co": [".posting-page", ".content"],
        "workday.com": ["[data-automation-id='jobPostingDescription']"],
        "smartrecruiters.com": [".job-description", ".jobad-description"],
    }

    for site, site_selectors in selectors.items():
        if site in domain:
            for sel in site_selectors:
                el = soup.select_one(sel)
                if el:
                    return el.get_text(separator="\n", strip=True)
    return None


def _extract_generic(soup: BeautifulSoup) -> Optional[str]:
    """Try generic job description selectors."""
    generic_selectors = [
        ".job-description",
        ".jd-content",
        ".job-details",
        "#job-description",
        "#job-details",
        "[class*='jobDescription']",
        "[class*='job-description']",
        "[data-testid='job-description']",
    ]

    for sel in generic_selectors:
        el = soup.select_one(sel)
        if el:
            text = el.get_text(separator="\n", strip=True)
            if len(text) > 100:
                return text
    return None


def _clean_text(text: str) -> str:
    """Clean extracted text."""
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' {2,}', ' ', text)
    text = text.replace('\xa0', ' ')
    return text.strip()
