import asyncio
import json
import logging
from functools import wraps
from typing import Any

import anthropic
from anthropic import AsyncAnthropic
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.config import get_settings
from app.exceptions import AIServiceError
from app.utils.json_parser import parse_json_response

logger = logging.getLogger(__name__)

client = AsyncAnthropic()


def retry_on_failure(max_retries: int = 3, backoff_base: int = 2):
    """Retry decorator for Claude API calls with exponential backoff."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        wait_time = backoff_base**attempt
                        logger.warning(
                            f"Claude API attempt {attempt + 1} failed: {e}. Retrying in {wait_time}s"
                        )
                        await asyncio.sleep(wait_time)
            logger.error(f"Claude API failed after {max_retries} attempts: {last_error}")
            raise last_error

        return wrapper

    return decorator


def _get_model(task_type: str = "default") -> str:
    settings = get_settings()
    model_map = {
        "default": settings.ai_model_default,
        "deep": settings.ai_model_deep,
        "content": settings.ai_model_content,
    }
    return model_map.get(task_type, settings.ai_model_default)


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
async def call_claude(prompt: str, max_tokens: int = 2000, task_type: str = "default") -> str:
    try:
        message = await client.messages.create(
            model=_get_model(task_type),
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text
    except (anthropic.RateLimitError, anthropic.InternalServerError):
        raise
    except anthropic.APIError as e:
        logger.error("Claude API error: %s", e)
        raise AIServiceError(f"Claude API error: {e}", cause=e) from e


@retry_on_failure(max_retries=3)
async def analyze_jd(jd_text: str, profile: dict[str, Any]) -> dict | None:
    level = profile.get("experience_level", "Mid")
    level_hint = LEVEL_CONTEXT.get(level, LEVEL_CONTEXT["Mid"])

    prompt = f"""You are an expert career coach and ATS resume analyst.

EVALUATION CONTEXT: {level_hint}

CANDIDATE PROFILE:
{json.dumps(profile, indent=2)}

JOB DESCRIPTION:
{jd_text}

Return ONLY valid JSON (no markdown, no backticks, no extra text):
{{
  "b2c_check": true,
  "b2c_reason": "",
  "ats_score": 75,
  "fit_score": 7.5,
  "fit_reasoning": "3-4 sentences explaining this score. Reference specific skill matches, domain fit, seniority alignment, and red flags. Be honest about gaps.",
  "salary_range": "XX-YY LPA",
  "keywords_matched": ["keyword1", "keyword2"],
  "keywords_missing": ["keyword3"],
  "resume_suggestions": ["max 3 specific actionable suggestions referencing exact resume sections"],
  "resume_suggestion_impact": "high or medium or low or none",
  "customize_recommendation": "Send master resume" or "Make 2-3 tweaks: ..." or "Needs deep customization",
  "cover_letter_draft": "Full 250-350 word cover letter. Structure: Subject line, Dear [name if in JD else Hiring Manager], Para 1 (why this role), Para 2 (2-3 achievements with numbers), Para 3 (closing). End with signature block using exact placeholders: [CANDIDATE_NAME] then [CANDIDATE_PHONE] then [CANDIDATE_LINKEDIN] each on new lines.",
  "interview_angle": "Key story to prepare...",
  "company_name": "extracted from JD text",
  "role_title": "extracted from JD text",
  "hiring_manager": "name if explicitly in JD, else Hiring Manager"
}}

RULES:
- resume_suggestions: maximum 3 items. Each must reference a specific section/bullet. If ATS > 85, say "Resume is well-matched for this role" and return empty array.
- resume_suggestion_impact: "high" if ATS would improve 10%+, "medium" 5-10%, "low" <5%, "none" if already strong.
- salary_range: estimate based on role title, seniority, company type, Bangalore market. Use "Unable to estimate" if not enough info.
- cover_letter_draft: Do NOT invent contact details. Use placeholders [CANDIDATE_NAME], [CANDIDATE_PHONE], [CANDIDATE_LINKEDIN] exactly as shown. If no hiring manager name is explicitly in the JD, use "Dear Hiring Manager". NEVER guess names.
- hiring_manager: Return the name ONLY if explicitly found in the JD text. Otherwise return "Hiring Manager".
- Never use the em dash character anywhere in your response. Use commas, periods, or regular hyphens instead.
- fit_reasoning must be specific, not generic. Reference actual skills and requirements from the JD."""

    result = await call_claude(prompt, max_tokens=4000)
    parsed = parse_json_response(result)

    # Safety net: strip em dashes from all string values
    if parsed:
        for key, value in parsed.items():
            if isinstance(value, str):
                parsed[key] = value.replace("\u2014", ", ").replace("\u2013", ", ")

    return parsed


@retry_on_failure(max_retries=3)
async def deep_resume_analysis(jd_text: str, resume_text: str, profile: dict[str, Any]) -> dict | None:
    """Deep resume vs JD analysis with specific rewrite suggestions."""
    level = profile.get("experience_level", "Mid")
    level_hint = LEVEL_CONTEXT.get(level, LEVEL_CONTEXT["Mid"])

    prompt = f"""You are an expert ATS resume analyst.

EVALUATION CONTEXT: {level_hint}

CANDIDATE RESUME:
{resume_text[:8000]}

JOB DESCRIPTION:
{jd_text}

Analyze how well this resume matches the JD. Return ONLY valid JSON:
{{
  "overall_match_score": 75,
  "section_scores": {{
    "skills_match": 80,
    "experience_relevance": 70,
    "education_fit": 60,
    "keywords_coverage": 75
  }},
  "ats_pass_likelihood": "High",
  "critical_gaps": ["gap1", "gap2"],
  "rewrite_suggestions": [
    {{
      "section": "Experience - Company Name",
      "current": "exact current bullet text from resume",
      "suggested": "improved version with metrics and keywords",
      "reason": "1 sentence on why this improves fit",
      "priority": "must-change"
    }}
  ],
  "keywords_to_add": ["keyword1"],
  "keywords_present": ["keyword2"],
  "executive_summary": "3-4 sentence overview of resume-JD fit"
}}

RULES:
- Maximum 5 rewrite_suggestions, ranked by impact (must-change first, then should-change, then nice-to-have)
- Rewrites must be factually defensible. Never invent metrics or experiences not in the resume.
- These are SUGGESTIONS only, clearly marked as such.
- priority values: "must-change", "should-change", "nice-to-have"
- Never use the em dash character. Use commas, periods, or hyphens.
- If resume is already a strong match, return 0-1 suggestions and say so in executive_summary."""

    result = await call_claude(prompt, max_tokens=4000, task_type="deep")
    return parse_json_response(result)


@retry_on_failure(max_retries=3)
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
  "achievements": [{{"company": "...", "description": "...", "metric": "..."}}],
  "resume_keywords": ["keyword1", "keyword2", ...],
  "education": [{{"institution": "...", "degree": "...", "year": "..."}}],
  "alumni_networks": ["network1"],
  "career_narrative": "3-4 sentence career story",
  "experience_level": "Entry|Mid|Senior|Director|VP",
  "years_of_experience": 13
}}"""

    result = await call_claude(prompt, max_tokens=2000)
    return parse_json_response(result)


@retry_on_failure(max_retries=3)
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

    return await call_claude(prompt, max_tokens=500, task_type="content")


@retry_on_failure(max_retries=3)
async def generate_single_post(topic: str, content_type: str, profile: Any) -> str | None:
    """Generate a single LinkedIn post for shuffle/regeneration."""
    prompt = f"""Write a LinkedIn post about: {topic}

Content type: {content_type}
Author background: {profile.positioning_statement if profile else 'Growth leader in consumer tech'}

Requirements:
- 150-200 words
- Professional but conversational tone
- Include a hook in the first line
- End with a question or call to action
- No hashtags

Return ONLY the post text, no preamble."""

    return await call_claude(prompt, max_tokens=500, task_type="content")


@retry_on_failure(max_retries=3)
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


@retry_on_failure(max_retries=3)
async def research_company_structured(
    company_name: str, sector: str | None, profile: dict[str, Any]
) -> dict | None:
    """Research company and return structured JSON for DB population."""
    sector_hint = f" ({sector})" if sector else ""
    prompt = f"""Research {company_name}{sector_hint} and create a briefing for a job candidate.

CANDIDATE TARGETING: {profile.get('target_roles', [])}

Return ONLY valid JSON (no markdown, no backticks, no extra text):
{{
  "sector": "industry/sector (e.g. Fintech, EdTech)",
  "website": "company website URL or null if unknown",
  "hq_city": "headquarters city or null",
  "funding": "funding stage and amount (e.g. Series B, $50M) or null",
  "investors": ["investor1", "investor2"] or [],
  "stage": "Startup|Growth|Scale-up|Enterprise or null",
  "deep_dive_content": "Full structured brief with headers covering: 1) Company Overview (what they do, business model, scale), 2) Recent News & Developments, 3) Growth Challenges (what problems they're likely hiring for), 4) Team & Leadership, 5) Likely Interview Questions (5 specific questions), 6) 90-Day Plan Prompt, 7) Investor/Backer Info. Use clear headers. 400-800 words."
}}

RULES:
- Never use the em dash character. Use commas, periods, or hyphens.
- Be factual. If info is unknown, use null or empty array.
- deep_dive_content must be plain text with newlines, no markdown formatting."""

    result = await call_claude(prompt, max_tokens=4000, task_type="deep")
    parsed = parse_json_response(result)

    # Safety net: strip em dashes from all string values
    if parsed:
        for key, value in list(parsed.items()):
            if isinstance(value, str):
                parsed[key] = value.replace("\u2014", ", ").replace("\u2013", ", ")
            elif isinstance(value, list) and key == "investors":
                parsed[key] = [
                    v.replace("\u2014", ", ").replace("\u2013", ", ") if isinstance(v, str) else v
                    for v in value
                ]

    return parsed


@retry_on_failure(max_retries=3)
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
7. Follow-ups due today (with names & companies)
8. Keyword gaps from recent JD analysis and how to address them
9. Networking targets for today's deep-dive company, including 3 LinkedIn search suggestions
10. A short connection message template tailored to today's deep-dive company

Keep it concise. Use bullet points. Under 800 words."""

    return await call_claude(prompt, max_tokens=1500, task_type="content")


@retry_on_failure(max_retries=3)
async def analyze_jd_patterns(jd_texts: list[str], resume_keywords: list[str]) -> dict | None:
    prompt = f"""Analyze these {len(jd_texts)} job descriptions that scored 7+ fit.

JOB DESCRIPTIONS:
{chr(10).join([f"--- JD {i+1} ---{chr(10)}{jd[:2000]}" for i, jd in enumerate(jd_texts)])}

CANDIDATE'S CURRENT RESUME KEYWORDS:
{', '.join(resume_keywords)}

Return ONLY valid JSON:
{{
  "top_keywords": [
    {{"keyword": "cross-functional leadership", "frequency": 6, "in_jds": [1,2,3,4,5,6]}}
  ],
  "candidate_covers": ["keywords from resume_keywords that appear in JDs"],
  "gaps": ["keywords frequent in JDs but MISSING from resume_keywords"],
  "gap_recommendations": [
    "Add 'cohort analysis' to Mylo bullet — you did RFM segmentation there",
    "Add 'marketplace dynamics' to summary — relevant from Pocket FM content marketplace"
  ],
  "coverage_score": 85
}}

Rank keywords by frequency. Include ALL keywords appearing in 3+ JDs."""

    result = await call_claude(prompt, max_tokens=3000)
    return parse_json_response(result)


@retry_on_failure(max_retries=3)
async def generate_interview_prep(
    company_name: str,
    role_title: str,
    jd_text: str,
    company_intel: str,
    profile: dict[str, Any],
) -> str | None:
    prompt = f"""Generate a comprehensive interview preparation document.

COMPANY: {company_name}
ROLE: {role_title}

JD:
{jd_text[:3000]}

COMPANY INTEL:
{company_intel[:2000] if company_intel else 'No prior research available'}

CANDIDATE PROFILE:
- Name: {profile.get('full_name', 'N/A')}
- Positioning: {profile.get('positioning_statement', 'N/A')}
- Core Skills: {', '.join(profile.get('core_skills', []))}
- Key Achievements: {json.dumps(profile.get('achievements', {}), indent=2)[:1500]}

Generate:

## 1. Company Context (3-4 sentences)
Why this company, what stage, what challenges

## 2. Why This Role Exists
What problem they're solving by hiring

## 3. Top 5 Interview Questions + Your STAR Answers
Use SPECIFIC examples from the candidate's experience.
Format: Q → Situation → Task → Action → Result

## 4. 90-Day Plan
First 30 days / 60 days / 90 days framework

## 5. Smart Questions To Ask Them
3 questions that show research and strategic thinking

## 6. Key Numbers To Have Ready
From candidate's experience that are relevant to this role

## 7. Gaps To Manage
Where your experience doesn't match JD + how to address it

Be specific. Use real numbers. No generic filler."""

    return await call_claude(prompt, max_tokens=4000)


@retry_on_failure(max_retries=3)
async def generate_market_intel(company_names: list[str]) -> str | None:
    prompt = f"""You are a market intelligence analyst for a job seeker targeting 
B2C consumer tech companies in Bangalore, India.

TARGET COMPANIES: {', '.join(company_names)}

For each company, research and provide:
- Recent news (last 2 weeks): funding, product launches, partnerships
- Leadership changes: new hires, departures at CXO/VP level
- Hiring signals: are they actively posting growth/marketing roles?
- Any layoffs or hiring freezes?

Also include:
- NEW B2C consumer tech companies in Bangalore that recently raised Series A/B/C
- Companies recently posting Head of Growth / VP Growth / Director Growth roles

Format as a readable digest. Be specific with names and dates.
Mark each company as 🟢 (actively hiring), 🟡 (stable), or 🔴 (freezing/laying off)."""

    return await call_claude(prompt, max_tokens=4000, task_type="content")


@retry_on_failure(max_retries=3)
async def generate_linkedin_post(
    topic_title: str,
    category: str,
    angle: str | None,
    profile: dict[str, Any],
    stories: list,
    avoid_specific_numbers: bool = True,
    instruction: str | None = None,
) -> str | None:
    """Generate a LinkedIn post with humanization rules."""

    stories_context = ""
    if stories:
        stories_context = "\n\nPERSONAL STORIES TO WEAVE IN (use naturally, don't force):\n"
        for s in stories[:2]:
            text = getattr(s, "story_text", str(s))[:200] if s else ""
            stories_context += f"- {text}...\n"

    instruction_text = ""
    if instruction:
        instruction_text = f"\n\nSPECIAL INSTRUCTION: {instruction}"

    number_guidance = ""
    if avoid_specific_numbers:
        number_guidance = """
IMPORTANT - NUMBER USAGE:
- DON'T say: "$7M budget", "$200M ARR", "40-person team"
- DO say: "large-scale budget", "significant revenue", "sizable team"
- Only use specific numbers when they're the POINT of the post (e.g., "9-month payback")
"""

    prompt = f"""Write a LinkedIn post about this topic.

TOPIC: {topic_title}
CATEGORY: {category}
ANGLE: {angle or 'thoughtful observation'}

AUTHOR CONTEXT:
{json.dumps(profile, indent=2, default=str)}
{stories_context}
{instruction_text}

HUMANIZATION RULES (CRITICAL - follow exactly):
1. NEVER use em-dashes (—)
2. NEVER start with "I"
3. NEVER use "In my experience...", "Here's the truth...", "Let me tell you..."
4. DO start with a statement, observation, or provocative question
5. DO include ONE incomplete sentence or fragment
6. DO admit uncertainty somewhere ("I'm still figuring this out", "I might be wrong")
7. DO end with a genuine question (not rhetorical)
8. Keep it 150-250 words
9. No hashtags
10. No emojis in first line
{number_guidance}

STRUCTURE VARIETY (don't always use the same pattern):
- Sometimes: Hook → Story → Insight → Question
- Sometimes: Observation → Counter-point → Personal take
- Sometimes: Question → My answer → Why I think this → Your turn
- Sometimes: Specific moment → Zoom out → Lesson

Write the post now. Return ONLY the post text, nothing else."""

    response = await client.messages.create(
        model=_get_model("content"),
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )

    return response.content[0].text.strip()


@retry_on_failure(max_retries=3)
async def generate_content_studio_topics(
    profile: dict[str, Any],
    categories: list[str] | None = None,
    avoid_specific_numbers: bool = True,
    recent_topics: list[str] | None = None,
) -> list[dict[str, Any]] | None:
    """Generate Content Studio v2 topics with angle and suggested_creative."""
    cats = categories or ["Growth", "Career", "Leadership", "GenAI", "Industry", "Personal"]
    cats_str = "|".join(cats)

    recent_context = ""
    if recent_topics:
        recent_context = (
            "\n\nAVOID these recent topics (too similar):\n"
            + "\n".join(f"- {t}" for t in recent_topics[:10])
        )

    number_guidance = ""
    if avoid_specific_numbers:
        number_guidance = """CRITICAL NUMBER AVOIDANCE RULES (apply to every topic):

NEVER mention specific dollar amounts ($7M, $200M, $1.5B, etc.)
NEVER mention specific percentages (40%, 13%, etc.)
NEVER mention specific team sizes (40-person team, 150+ workforce)
NEVER mention specific timeframes with numbers (2.5 years, 6 months)

INSTEAD USE:

"multi-million dollar budgets" instead of "$7M"
"significant revenue growth" instead of "$200M ARR"
"large cross-functional teams" instead of "40-person team"
"rapid scaling" instead of "10x growth"

If the user's profile contains specific numbers, ABSTRACT them. The topics should be about THEMES, not specific metrics from the user's resume.

---

"""

    prompt = f"""{number_guidance}Generate 7 LinkedIn post topics for this profile.

PROFILE:
{json.dumps(profile, indent=2, default=str)}

CATEGORIES TO USE (pick from): {cats_str}
{recent_context}

Return ONLY valid JSON:
{{
  "topics": [
    {{
      "topic_title": "short catchy title",
      "category": "one of the categories",
      "angle": "contrarian|how-to|story|question|observation",
      "suggested_creative": "text|image|carousel"
    }}
  ]
}}"""

    result = await call_claude(prompt, max_tokens=1000, task_type="content")
    data = parse_json_response(result)
    if not data:
        return None
    return data.get("topics", [])


@retry_on_failure(max_retries=3)
async def generate_content_topics(profile: dict[str, Any]) -> list[dict[str, str]] | None:
    prompt = f"""Generate 7 LinkedIn post topics for this profile.

PROFILE:
{json.dumps(profile, indent=2)}

Return ONLY valid JSON:
{{
  "topics": [
    {{"topic": "...", "category": "Growth|GenAI|Strategy|Industry|Personal"}}
  ]
}}"""

    result = await call_claude(prompt, max_tokens=1000, task_type="content")
    data = parse_json_response(result)
    if not data:
        return None
    return data.get("topics")


@retry_on_failure(max_retries=3)
async def generate_midday_check(data: dict[str, Any]) -> str | None:
    prompt = f"""Generate a mid-day accountability check for a job seeker.

Recent activity data:
{json.dumps(data, indent=2, default=str)}

If activity is low (0 applications for 2+ days): firm but encouraging escalation.
If activity is decent: quick encouragement + 1 actionable task for next 2 hours.
Keep it under 200 words."""

    return await call_claude(prompt, max_tokens=400, task_type="content")


@retry_on_failure(max_retries=3)
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

    return await call_claude(prompt, max_tokens=1200, task_type="content")
