"""Seed initial data for Abhinav Jain's job search."""
import asyncio
from datetime import date, timedelta

from sqlalchemy import select

from app.auth.jwt_handler import hash_password
from app.database import AsyncSessionLocal
from app.models import Company, ContentCalendar, JDKeyword, ProfileDNA, User


async def seed() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == "abhinav.jain.iitd@gmail.com"))
        if result.scalar_one_or_none():
            print("User already exists, skipping seed")
            return

        user = User(
            email="abhinav.jain.iitd@gmail.com",
            hashed_password=hash_password("TempPassword1"),
            full_name="Abhinav Jain",
            is_active=True,
            onboarding_completed=True,
            telegram_chat_id=7019499883,
        )
        db.add(user)
        await db.flush()

        profile = ProfileDNA(
            user_id=user.id,
            full_name="Abhinav Jain",
            positioning_statement=(
                "Growth leader with 13+ years in consumer tech. Built GenAI creative production at Pocket FM "
                "and automated retention systems at Mylo."
            ),
            target_roles=[
                "VP Growth",
                "Head of Growth",
                "Director Growth",
                "Chief of Staff",
                "Business Head",
            ],
            target_locations=["Bengaluru"],
            target_salary_range="90 LPA",
            core_skills=[
                "User Acquisition at Scale",
                "CAC/LTV/ROAS Optimization",
                "Performance Marketing",
                "GenAI Operations",
                "0-to-1 Vertical Builds",
                "P&L Management",
                "Cross-functional Leadership",
                "CRM & Lifecycle Marketing",
            ],
            tools_platforms=["Meta Ads", "Google Ads", "TikTok Ads", "Product Analytics"],
            industries=[
                "Consumer Tech",
                "B2C Marketplaces",
                "D2C",
                "Fintech Consumer",
                "EdTech",
                "HealthTech Consumer",
            ],
            resume_keywords=[
                "CAC",
                "LTV",
                "ROAS",
                "user acquisition",
                "performance marketing",
                "GenAI",
                "growth strategy",
                "P&L",
                "cross-functional",
                "0-to-1",
                "retention",
                "CRM",
                "lifecycle",
                "funnel optimization",
                "A/B testing",
                "data-driven",
                "category management",
                "stakeholder management",
            ],
            education=[
                {"institution": "IIT Delhi", "degree": "B.Tech + M.Tech", "year": "2012"},
                {"institution": "IIM Calcutta", "degree": "Executive Program for Young Managers", "year": "2015"},
            ],
            alumni_networks=["IIT Delhi", "IIM Calcutta", "GrowthX", "Pocket FM"],
            experience_level="Director",
            years_of_experience=13,
            job_search_type="Level_Up",
        )
        db.add(profile)

        companies_data = [
            ("Swiggy", 1, "Public", "Food & Delivery"),
            ("Flipkart", 1, "Pre-IPO", "E-commerce"),
            ("CRED", 1, "Late-stage", "Fintech Consumer"),
            ("Meesho", 1, "Late-stage", "Social Commerce"),
            ("Zepto", 1, "Late-stage", "Quick Commerce"),
            ("PhonePe", 1, "Public", "Fintech Consumer"),
            ("Dream11", 1, "Late-stage", "Gaming"),
            ("Ather Energy", 1, "Public", "EV Consumer"),
            ("BigBasket", 1, "Acquired", "Grocery"),
            ("Rapido", 1, "Late-stage", "Mobility"),
            ("Delhivery", 1, "Public", "Logistics"),
            ("Smallcase", 2, "Series C", "Fintech Consumer"),
            ("NoBroker", 2, "Series D", "PropTech"),
            ("Country Delight", 2, "Series D", "D2C Food"),
            ("Wakefit", 2, "Series D", "D2C Home"),
            ("Lenskart", 2, "Late-stage", "D2C Eyewear"),
            ("Supertails", 2, "Series C", "Pet Care"),
            ("Park+", 2, "Series C", "Mobility"),
            ("Kutumb", 2, "Series C", "Social"),
            ("HealthifyMe", 2, "Series C", "HealthTech"),
            ("Cult.fit", 2, "Series D", "Fitness"),
            ("Navi", 2, "Series C", "Fintech"),
            ("Jupiter", 2, "Series C", "Fintech Consumer"),
            ("Simplilearn", 2, "Acquired", "EdTech"),
            ("Uber", 3, "Public", "Mobility"),
            ("Netflix", 3, "Public", "Entertainment"),
            ("Spotify", 3, "Public", "Entertainment"),
            ("Amazon Retail", 3, "Public", "E-commerce"),
            ("Google Consumer", 3, "Public", "Tech"),
            ("ITC", 3, "Public", "FMCG Conglomerate"),
            ("Jio Hotstar", 3, "Public", "Entertainment"),
            ("Tata Consumer Products", 3, "Public", "FMCG"),
        ]

        for name, lane, stage, sector in companies_data:
            db.add(
                Company(
                    user_id=user.id,
                    name=name,
                    lane=lane,
                    stage=stage,
                    sector=sector,
                    b2c_validated=True,
                    hq_city="Bengaluru",
                )
            )

        categories = ["Growth", "GenAI", "Strategy", "Industry", "Personal", "Growth"]
        topics = [
            "The one metric that changed how I think about user acquisition",
            "GenAI isn't replacing marketers. It's creating a new breed of them.",
            "Why 0-to-1 is harder than 1-to-100 (and what most people get wrong)",
            "India's B2C landscape in 2026: who's winning and why",
            "What 2.5 years at a hypergrowth startup taught me about myself",
            "CAC is a vanity metric. Here's what actually matters.",
            "How we built a GenAI creative pipeline that produces 10K+ variations",
            "The Chief of Staff role is the most misunderstood in tech",
            "Quick commerce vs traditional e-commerce: a growth framework",
            "Why I left a comfortable role and what I'm looking for next",
            "Performance marketing at scale: lessons from managing $7M/month",
            "AI-first operations: practical lessons (not hype)",
            "Building teams in chaos: what works when everything is on fire",
            "The B2C consumer tech stack in 2026",
        ]

        start_date = date.today() + timedelta(days=1)
        for i, topic in enumerate(topics):
            db.add(
                ContentCalendar(
                    user_id=user.id,
                    scheduled_date=start_date + timedelta(days=i),
                    topic=topic,
                    category=categories[i % len(categories)],
                    status="Planned",
                )
            )

        keywords_data = [
            ("cross-functional leadership", 8, "Leadership", True),
            ("stakeholder management", 8, "Leadership", True),
            ("P&L ownership", 7, "Strategy", True),
            ("growth strategy", 7, "Growth", True),
            ("data-driven decisions", 6, "Analytics", True),
            ("0-to-1 builds", 6, "Execution", True),
            ("performance marketing", 5, "Growth", True),
            ("CAC/LTV/ROAS", 5, "Growth", True),
            ("team building", 5, "Leadership", True),
            ("strategic planning", 5, "Strategy", True),
            ("full-funnel marketing", 5, "Growth", True),
            ("A/B testing", 5, "Growth", True),
            ("executive communication", 4, "Leadership", True),
            ("GenAI operations", 4, "Technology", True),
            ("category management", 4, "Strategy", True),
            ("CRM lifecycle", 4, "Growth", True),
            ("user journey mapping", 4, "Product", True),
            ("OKR setting", 4, "Strategy", True),
            ("influence without authority", 3, "Leadership", False),
            ("navigate ambiguity", 3, "Leadership", False),
            ("retention marketing", 3, "Growth", True),
            ("monetization strategy", 3, "Strategy", True),
            ("product analytics", 3, "Analytics", True),
            ("board presentations", 3, "Leadership", True),
            ("marketing automation", 3, "Growth", True),
        ]

        for keyword, freq, category, in_profile in keywords_data:
            db.add(
                JDKeyword(
                    user_id=user.id,
                    keyword=keyword,
                    frequency_count=freq,
                    category=category,
                    in_profile_dna=in_profile,
                )
            )

        await db.commit()
        print(
            f"Seeded: 1 user, 1 profile, {len(companies_data)} companies, {len(topics)} content topics, {len(keywords_data)} keywords",
        )


if __name__ == "__main__":  # pragma: no cover - manual script
    asyncio.run(seed())
