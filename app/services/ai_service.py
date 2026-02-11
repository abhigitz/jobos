import json
import logging
from typing import Any

import anthropic
from anthropic import AsyncAnthropic
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)

client = AsyncAnthropic()


LEVEL_CONTEXT = {
    "Entry": "Evaluate for an entry-level candidate. Emphasize transferable skills, learning potential, education.",
    "Mid": "Evaluate for a mid-level professional (3-7 yrs). Balance skills with growth potential.",
    "Senior": "Evaluate for a senior professional (8-12 yrs). Emphasize depth and leadership.",
    "Director": "Evaluate for Director/VP level. Emphasize P&L, strategic leadership, scale.",
    "VP": "Evaluate for VP/C-suite. Emphasize business transformation, org building.",
}


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((anthropic.RateLimitError, anthropic.InternalServerError)),
)
async def call_claude(prompt: str, max_tokens: int = 2000) -> str | None:
    try:
        message = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text
    except (anthropic.RateLimitError, anthropic.InternalServerError):
        raise
    except anthropic.APIError as e:
        logger.error(f"Claude API error: {e}")
        return None


def parse_json_response(text: str | None) -> dict | None:
    if text is None:
        return None
    clean = text.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON: {clean[:200]}")
        return None


async def analyze_jd(jd_text: str, profile: dict[str, Any]) -> dict | None:
    level = profile.get("experience_level", "Mid")
    level_hint = LEVEL_CONTEXT.get(level, LEVEL_CONTEXT["Mid"])

    prompt = f"""You are an expert career coach and ATS resume analyst.

EVALUATION CONTEXT: {level_hint}

CANDIDATE PROFILE:
{json.dumps(profile, indent=2)}

JOB DESCRIPTION:
{jd_text}

Return ONLY valid JSON (no markdown, no backticks):
{{
  "b2c_check": true,
  "b2c_reason": "...",
  "ats_score": 75,
  "fit_score": 7.5,
  "keywords_matched": ["keyword1", "keyword2"],
  "keywords_missing": ["keyword3"],
  "customize_recommendation": "Send master resume" or "Make 2-3 tweaks: ..." or "Needs deep customization",
  "cover_letter_draft": "120-word draft...",
  "interview_angle": "Key story to prepare...",
  "company_name": "extracted from JD",
  "role_title": "extracted from JD"
}}"""

    result = await call_claude(prompt, max_tokens=2000)
    return parse_json_response(result)


async def extract_profile(resume_text: str) -> dict | None:
    prompt = f"""Extract a structured professional profile from this resume/text.

TEXT:
{resume_text}

Return ONLY valid JSON:
{{
  "full_name": "...",
  "positioning_statement": "1-2 sentence summary",
  "target_roles": ["role1", "role2"],
  "core_skills": ["skill1", "skill2"],
  "tools_platforms": ["tool1"],
  "industries": ["industry1"],
  "achievements": [{{"company": "...", "achievement": "...", "metric": "..."}}],
  "resume_keywords": ["keyword1", "keyword2", ...],
  "education": [{{"institution": "...", "degree": "...", "year": "..."}}],
  "alumni_networks": ["network1"],
  "career_narrative": "3-4 sentence career story",
  "experience_level": "Entry|Mid|Senior|Director|VP",
  "years_of_experience": 13
}}"""

    result = await call_claude(prompt, max_tokens=2000)
    return parse_json_response(result)


async def generate_content_draft(topic: str, category: str, profile: dict[str, Any]) -> str | None:
    prompt = f"""Write a 150-200 word LinkedIn post about this topic.

TOPIC: {topic}
CATEGORY: {category}
AUTHOR PROFILE: {json.dumps(profile, indent=2)}

Write in first person, conversational but professional tone. 
Include 1-2 specific insights from the author's experience.
End with a question or call-to-action.
No hashtags. No emojis in the first line.
Return ONLY the post text, nothing else."""

    return await call_claude(prompt, max_tokens=500)


async def generate_company_deep_dive(company_name: str, sector: str | None, profile: dict[str, Any]) -> str | None:
    prompt = f"""Research and create a briefing on {company_name} ({sector}) for a job candidate.

CANDIDATE TARGETING: {profile.get('target_roles', [])}

Create a structured brief covering:
1. Company Overview (what they do, business model, scale)
2. Recent News & Developments
3. Growth Challenges (what problems they're likely hiring for)
4. Team & Leadership
5. Likely Interview Questions (5 specific questions for this company)
6. 90-Day Plan Prompt ("What would you do in first 90 days as [role] here?")
7. Investor/Backer Info

Return as structured text with clear headers."""

    return await call_claude(prompt, max_tokens=3000)


async def generate_morning_briefing(data: dict[str, Any]) -> str | None:
    prompt = f"""Generate a morning briefing for a job seeker based on this data:

{json.dumps(data, indent=2, default=str)}

Include:
1. Today's priority actions (jobs to apply, follow-ups due)
2. 3 connection targets for today
3. 3-4 engagement targets (posts to comment on)
4. Reminder: Update Naukri profile
5. Streak counter based on daily_logs
6. Today's company deep-dive preview

Keep it concise. Use bullet points. Under 800 words."""

    return await call_claude(prompt, max_tokens=1500)


async def generate_midday_check(data: dict[str, Any]) -> str | None:
    prompt = f"""Generate a mid-day accountability check for a job seeker.

Recent activity data:
{json.dumps(data, indent=2, default=str)}

If activity is low (0 applications for 2+ days): firm but encouraging escalation.
If activity is decent: quick encouragement + 1 actionable task for next 2 hours.
Keep it under 200 words."""

    return await call_claude(prompt, max_tokens=400)


async def generate_weekly_review(data: dict[str, Any]) -> str | None:
    prompt = f"""Generate a weekly review for a job seeker.

This week's data:
{json.dumps(data, indent=2, default=str)}

Include:
1. Verdict: On track or off track?
2. Key wins this week
3. Gaps to address
4. Specific adjustments for next week
5. Reflection: "What energized you? What drained you?"

Be direct and actionable. Under 600 words."""

    return await call_claude(prompt, max_tokens=1200)
