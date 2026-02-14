import asyncio
import json
import logging
from datetime import datetime
from functools import wraps
from typing import Any, Dict, List, Optional

import anthropic
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.config import get_settings
from app.exceptions import AIServiceError
from app.utils.json_parser import parse_json_response

logger = logging.getLogger(__name__)

client = AsyncAnthropic()
openai_client: Optional[AsyncOpenAI] = None


def _get_openai_client() -> AsyncOpenAI:
    global openai_client
    if openai_client is None:
        settings = get_settings()
        openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    return openai_client


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
        if not message.content or len(message.content) == 0:
            raise AIServiceError("Claude returned empty response")
        if not hasattr(message.content[0], "text"):
            raise AIServiceError("Claude response missing text field")
        return message.content[0].text
    except (anthropic.RateLimitError, anthropic.InternalServerError):
        raise
    except anthropic.APIError as e:
        logger.error("Claude API error: %s", e)
        raise AIServiceError(f"Claude API error: {e}", cause=e) from e


@retry_on_failure(max_retries=3)
async def analyze_jd(jd_text: str, profile: dict[str, Any]) -> Optional[dict]:
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
async def deep_resume_analysis(jd_text: str, resume_text: str, profile: dict[str, Any]) -> Optional[dict]:
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
async def extract_profile(resume_text: str) -> Optional[dict]:
    prompt = f"""Extract a structured professional profile from this resume/text.

RULES:
- For dual degrees (e.g. B.Tech + M.Tech), create SEPARATE entries for each degree.
- Do not combine multiple degrees into a single entry. Extract ALL education entries.

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
  "education": [
    {{"institution": "IIT Delhi", "degree": "B.Tech", "year": "2012"}},
    {{"institution": "IIT Delhi", "degree": "M.Tech", "year": "2012"}}
  ],
  "alumni_networks": ["network1"],
  "career_narrative": "3-4 sentence career story",
  "experience_level": "Entry|Mid|Senior|Director|VP",
  "years_of_experience": 13
}}"""

    result = await call_claude(prompt, max_tokens=2000)
    return parse_json_response(result)


@retry_on_failure(max_retries=3)
async def generate_content_draft(topic: str, category: str, profile: dict[str, Any]) -> Optional[str]:
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
async def generate_single_post(topic: str, content_type: str, profile: Any) -> Optional[str]:
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
async def generate_company_deep_dive(company_name: str, sector: Optional[str], profile: dict[str, Any]) -> Optional[str]:
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
    company_name: str, sector: Optional[str], profile: dict[str, Any]
) -> Optional[dict]:
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


def _build_company_research_prompt(company_name: str, custom_questions: Optional[str]) -> str:
    """Build the comprehensive research prompt."""
    custom_section = ""
    if custom_questions:
        custom_section = f"""
CUSTOM QUESTIONS TO ANSWER IN DETAIL:
{custom_questions}

For EACH custom question above, provide a thorough 200-300 word answer with specific data points, numbers, and sources where relevant. Include in custom_answers.questions_answered as objects with "question" and "answer" keys.
"""
    return f"""You are a senior strategy consultant at McKinsey preparing a comprehensive company intelligence briefing for a VP-level candidate interviewing at {company_name}.

This is NOT a surface-level summary. This is a deep-dive that MUST include:
- Specific numbers and metrics with sources
- Current data (USE WEB SEARCH to gather latest financials, news, filings, DRHP)
- Nuanced competitive analysis
- Actionable interview insights

STEP 1: Use the web_search tool to gather current data on {company_name} - financials, recent news, IPO/DRHP if applicable, competitor updates, leadership changes.
STEP 2: Synthesize all gathered data into the structured JSON below.

REQUIREMENTS BY SECTION:

1. COMPANY OVERVIEW (overview + company):
   - Full company timeline: founding year, key milestones (funding rounds, product launches, pivots), current state
   - Latest financials with SPECIFIC numbers: Revenue, GMV, MAU, Orders (use web search for FY24/FY25 data)
   - IPO/DRHP data if applicable (filing status, key metrics from DRHP)
   - Org structure and business verticals
   - Monetization breakdown with P&L contribution percentages where known

2. COMPETITORS (minimum 5-6 competitors):
   - Revenue comparison, market share, threat level for each
   - At least 5 specific strengths and 3 specific weaknesses per competitor
   - Unique hex color code for each competitor (e.g. #3B82F6, #10B981)

3. USER PERSONAS (minimum 4 distinct personas):
   - Include: buyer, seller, reseller, first-time user (or equivalent for the business model)
   - Detailed demographics, behaviors, goals, pain points for each
   - Platform usage patterns

4. OPPORTUNITIES:
   - At least 5 market gaps with specific opportunity descriptions
   - Growth levers with implementation details
   - Competitive threats with mitigation strategies
   - At least 5 strategic recommendations

5. INTERVIEW PREP:
   - 8-10 likely questions with detailed suggested angles
   - Talking points with supporting data
   - At least 5 red flags to avoid
   - At least 5 topics for further research
{custom_section}

Return ONLY valid JSON matching this EXACT structure (no markdown, no code fences, no preamble):

{{
  "company": {{
    "name": "{company_name}",
    "tagline": "One-line value proposition",
    "founded": "YYYY",
    "headquarters": "City, Country",
    "employees": "X+",
    "funding": "Total raised",
    "valuation": "Current valuation with year",
    "ceo": "CEO Name",
    "industry": "Industry"
  }},
  "overview": {{
    "timeline": "Full timeline from founding to present with key milestones",
    "business_model": "Detailed explanation of how the company makes money",
    "key_metrics": [
      {{"label": "Revenue", "value": "specific number", "growth": "YoY", "context": "FY24/FY25"}},
      {{"label": "GMV", "value": "specific number", "growth": "YoY", "context": "Annual"}},
      {{"label": "MAU/Users", "value": "specific number", "growth": "YoY", "context": "Monthly"}},
      {{"label": "Orders", "value": "specific number", "growth": "YoY", "context": "Annual"}}
    ],
    "ipo_drhp": "IPO/DRHP status and key data if applicable, else null",
    "org_structure": "Business verticals and org structure",
    "monetization_breakdown": "P&L contribution by segment with percentages",
    "recent_news": [
      {{"headline": "Recent development", "date": "Month YYYY", "impact": "Positive|Negative|Neutral"}}
    ],
    "strategic_priorities": ["Priority 1", "Priority 2", "Priority 3"]
  }},
  "competitors": [
    {{
      "name": "Competitor Name",
      "color": "#HEXCODE",
      "tagline": "Positioning",
      "model": "Business model",
      "revenue": "Revenue figure",
      "market_share": "X%",
      "strengths": ["5+ specific strengths"],
      "weaknesses": ["3+ specific weaknesses"],
      "threat_level": "High|Medium|Low"
    }}
  ],
  "positioning": {{
    "competitive_advantages": ["Advantage 1", "Advantage 2", "Advantage 3"],
    "market_position": "2-3 sentence description",
    "differentiation": "What makes them unique"
  }},
  "user_personas": [
    {{
      "name": "Persona - Descriptor",
      "emoji": "emoji",
      "age": "age range",
      "location": "geography",
      "income": "income range",
      "behavior": "Key behaviors",
      "goals": ["Goal 1", "Goal 2"],
      "pain_points": ["Pain 1", "Pain 2"],
      "platforms": "Where they engage"
    }}
  ],
  "opportunities": {{
    "market_gaps": [
      {{"gap": "Gap", "opportunity": "How to exploit", "difficulty": "High|Medium|Low"}}
    ],
    "growth_levers": ["Lever with implementation detail"],
    "threats": ["Threat 1", "Threat 2"],
    "competitive_threats": [
      {{"threat": "Threat", "mitigation": "Strategy"}}
    ],
    "strategic_recommendations": ["5+ recommendations"]
  }},
  "interview_prep": {{
    "likely_questions": [
      {{"question": "Question?", "suggested_angle": "Detailed approach with data"}}
    ],
    "talking_points": ["Point with supporting data"],
    "red_flags_to_avoid": ["5+ items"],
    "topics_to_research_further": ["5+ topics"]
  }},
  "custom_answers": {{
    "questions_answered": [
      {{"question": "Custom Q", "answer": "200-300 word detailed answer with data"}}
    ]
  }},
  "sources": ["Source 1", "Source 2"],
  "generated_at": "{datetime.utcnow().isoformat()}"
}}

CRITICAL RULES:
- Return ONLY the JSON object. No markdown, no ```json, no explanation before or after.
- Use web search to get CURRENT data. Do not rely on training data for financials or recent news.
- For India companies, use ₹ for currency.
- threat_level, difficulty: "High", "Medium", or "Low"
- impact: "Positive", "Negative", or "Neutral"
- Never use em dashes (—). Use commas, periods, or hyphens instead."""


async def _call_claude_with_web_search(prompt: str, max_tokens: int = 8000) -> str:
    """
    Call Claude with web search tool enabled for real-time data.
    Uses messages.create with web_search_20250305 server tool.
    """
    settings = get_settings()
    model = settings.ai_model_deep
    web_search_tool: Dict[str, Any] = {
        "type": "web_search_20250305",
        "name": "web_search",
        "max_uses": 8,
    }
    try:
        message = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
            tools=[web_search_tool],
            tool_choice={"type": "auto"},
        )
    except anthropic.BadRequestError as e:
        if "web_search" in str(e).lower() or "tool" in str(e).lower():
            logger.warning("Web search tool not available, falling back to standard completion: %s", e)
            return await call_claude(prompt, max_tokens=max_tokens, task_type="deep")
        raise

    if not message.content or len(message.content) == 0:
        raise AIServiceError("Claude returned empty response")

    text_parts: List[str] = []
    for block in message.content:
        if hasattr(block, "text") and block.text:
            text_parts.append(block.text)
        elif getattr(block, "type", None) == "tool_use":
            logger.info("Model requested tool_use (web search); server handles execution")
            continue

    result = "".join(text_parts)
    if not result:
        raise AIServiceError("Claude response contained no text content")
    return result


def _clean_em_dashes(obj: Any) -> Any:
    """Recursively strip em dashes from string values."""
    if isinstance(obj, str):
        return obj.replace("\u2014", ", ").replace("\u2013", ", ")
    if isinstance(obj, dict):
        return {k: _clean_em_dashes(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_em_dashes(x) for x in obj]
    return obj


@retry_on_failure(max_retries=3)
async def generate_company_quick_research(
    company_name: str, custom_questions: Optional[str] = None
) -> Optional[dict]:
    """
    Fast, cheap research using Claude Haiku.
    No web search - uses model knowledge only. Returns structured JSON.
    """
    prompt = f"""Generate a company research summary for {company_name}.

Return ONLY valid JSON (no markdown, no code fences) with this structure:
{{
  "company": {{
    "name": "{company_name}",
    "tagline": "One-line description",
    "founded": "Year",
    "headquarters": "City, Country",
    "employees": "Count",
    "funding": "Total raised",
    "valuation": "Latest valuation",
    "ceo": "CEO Name",
    "industry": "Industry"
  }},
  "overview": {{
    "business_model": "2-3 sentence description of how they make money",
    "key_metrics": [
      {{"label": "Revenue", "value": "₹X Cr", "growth": "+X% YoY", "context": "FY24"}},
      {{"label": "Users", "value": "XM+", "growth": "+X%", "context": "MAU"}},
      {{"label": "GMV", "value": "$XB", "growth": "+X%", "context": "Annual"}}
    ],
    "recent_news": [
      {{"headline": "Recent news headline", "date": "Month Year", "impact": "Positive"}}
    ],
    "strategic_priorities": ["Priority 1", "Priority 2", "Priority 3"]
  }},
  "competitors": [
    {{
      "name": "Competitor Name",
      "color": "#3B82F6",
      "tagline": "Their positioning",
      "model": "Business model",
      "revenue": "Revenue figure",
      "market_share": "X%",
      "strengths": ["Strength 1", "Strength 2", "Strength 3"],
      "weaknesses": ["Weakness 1", "Weakness 2"],
      "threat_level": "High"
    }}
  ],
  "positioning": {{
    "competitive_advantages": ["Advantage 1", "Advantage 2", "Advantage 3"],
    "market_position": "Description of market position",
    "differentiation": "What makes them unique"
  }},
  "user_personas": [
    {{
      "name": "Persona Name",
      "emoji": "👤",
      "age": "25-35",
      "location": "Location type",
      "income": "Income range",
      "behavior": "Key behaviors",
      "goals": ["Goal 1", "Goal 2"],
      "pain_points": ["Pain 1", "Pain 2"],
      "platforms": "Where they engage"
    }}
  ],
  "opportunities": {{
    "market_gaps": [{{"gap": "Gap description", "opportunity": "How to exploit", "difficulty": "Medium"}}],
    "growth_levers": ["Lever 1", "Lever 2"],
    "threats": ["Threat 1", "Threat 2"],
    "strategic_recommendations": ["Recommendation 1", "Recommendation 2"]
  }},
  "interview_prep": {{
    "likely_questions": [
      {{"question": "Interview question?", "suggested_angle": "How to approach"}}
    ],
    "talking_points": ["Point 1", "Point 2"],
    "red_flags_to_avoid": ["Avoid 1", "Avoid 2"],
    "topics_to_research_further": ["Topic 1", "Topic 2"]
  }},
  "custom_answers": {{"questions_answered": []}},
  "sources": ["AI Analysis based on training data"],
  "generated_at": "{datetime.utcnow().isoformat()}",
  "research_type": "quick"
}}

Include 3 competitors and 2 user personas. Be concise but accurate.
{f"Also briefly answer: {custom_questions}" if custom_questions else ""}

Return ONLY the JSON object, nothing else."""

    try:
        response = await client.messages.create(
            model="claude-haiku-4-20250514",
            max_tokens=2500,
            messages=[{"role": "user", "content": prompt}],
        )
        content = response.content[0].text
    except Exception as e:
        logger.exception("Quick research Claude Haiku call failed for %s: %s", company_name, e)
        raise

    # Clean up any markdown formatting
    if "```" in content:
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
    content = content.strip()

    parsed = parse_json_response(content)
    if parsed:
        return _clean_em_dashes(parsed)
    logger.error("Quick research failed to parse JSON for %s. Preview: %s", company_name, content[:500])
    return None


@retry_on_failure(max_retries=3)
async def generate_company_deep_research(
    company_name: str, custom_questions: Optional[str] = None
) -> Optional[dict]:
    """
    Generate comprehensive company research for VP/Head of Growth interview prep.
    Uses Claude with web search for real-time financials, news, DRHP data.
    Returns structured JSON matching the Company Deep Research schema.
    """
    prompt = _build_company_research_prompt(company_name, custom_questions)

    max_parse_retries = 2
    last_result: str = ""

    for parse_attempt in range(max_parse_retries + 1):
        try:
            result = await _call_claude_with_web_search(prompt, max_tokens=8000)
        except Exception as e:
            logger.exception("Company research AI call failed for %s: %s", company_name, e)
            raise

        last_result = result
        logger.info(
            "Company research AI response for %s (attempt %d): length=%d, preview=%s",
            company_name,
            parse_attempt + 1,
            len(result),
            result[:500] if result else "",
        )

        parsed = parse_json_response(result)

        if parsed:
            parsed = _clean_em_dashes(parsed)
            return parsed

        if parse_attempt < max_parse_retries:
            logger.warning(
                "JSON parse failed for %s, retrying with stricter instructions (attempt %d)",
                company_name,
                parse_attempt + 1,
            )
            prompt = prompt + "\n\nRETRY: Your previous response was not valid JSON. Return ONLY a single valid JSON object. No markdown, no code blocks, no extra text. Ensure all strings are properly escaped."

    logger.error(
        "Company research failed to parse JSON after %d attempts for %s. Response preview: %s",
        max_parse_retries + 1,
        company_name,
        last_result[:1000] if last_result else "N/A",
    )
    return None


@retry_on_failure(max_retries=3)
async def generate_morning_briefing(data: dict[str, Any]) -> Optional[str]:
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
async def analyze_jd_patterns(jd_texts: list[str], resume_keywords: list[str]) -> Optional[dict]:
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
) -> Optional[str]:
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
async def generate_market_intel(company_names: list[str]) -> Optional[str]:
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
    angle: Optional[str],
    profile: dict[str, Any],
    stories: list,
    avoid_specific_numbers: bool = True,
    instruction: Optional[str] = None,
) -> Optional[str]:
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

    if not response.content or len(response.content) == 0:
        raise AIServiceError("Claude returned empty response")
    if not hasattr(response.content[0], "text"):
        raise AIServiceError("Claude response missing text field")
    return response.content[0].text.strip()


@retry_on_failure(max_retries=3)
async def generate_content_studio_topics(
    profile: dict[str, Any],
    categories: Optional[List[str]] = None,
    avoid_specific_numbers: bool = True,
    recent_topics: Optional[List[str]] = None,
) -> Optional[List[Dict[str, Any]]]:
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
async def generate_content_topics(profile: dict[str, Any]) -> Optional[List[Dict[str, str]]]:
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
async def generate_midday_check(data: dict[str, Any]) -> Optional[str]:
    prompt = f"""Generate a mid-day accountability check for a job seeker.

Recent activity data:
{json.dumps(data, indent=2, default=str)}

If activity is low (0 applications for 2+ days): firm but encouraging escalation.
If activity is decent: quick encouragement + 1 actionable task for next 2 hours.
Keep it under 200 words."""

    return await call_claude(prompt, max_tokens=400, task_type="content")


@retry_on_failure(max_retries=3)
async def generate_weekly_review(data: dict[str, Any]) -> Optional[str]:
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
