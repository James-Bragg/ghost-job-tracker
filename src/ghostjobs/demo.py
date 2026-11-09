"""Fake-but-realistic data so you can try everything before you have API keys.

Simulates ~2 months of history: genuine jobs, long-running reposted adverts, a CV-harvesting
agency, adverts that have since been taken down, the same job syndicated on both boards,
and Adzuna salary estimates.
"""

import random
from datetime import timedelta

from sqlmodel import Session, delete

from ghostjobs.db import Posting, utcnow

DETAILED = (
    "{company} is hiring a {title} to join our {team} team in {town}. You'll report to "
    "{manager}, our {team} lead, and work alongside four colleagues. Day to day you will "
    "{task}. We use {tools}. You'll get a structured 3-month onboarding plan, a named mentor, "
    "25 days holiday plus bank holidays, and a pension with 5% employer contribution. "
    "Interviews are a 30-minute video call followed by an in-person chat and a short practical "
    "task. We aim to give everyone feedback within a week of applying. Start date is January."
)

GHOSTY = [
    "Join our talent pool! We are always looking for talented rockstars to join our dynamic "
    "team in a fast-paced environment. Competitive salary.",
    "Register your interest for future opportunities with a leading client. Self-starter "
    "needed. Competitive salary and benefits.",
    "Our client is building a pipeline of junior candidates for upcoming roles. Ongoing "
    "recruitment on a rolling basis.",
]

GENUINE = [
    (
        "Junior Python Developer",
        "Northgate Logistics",
        "data",
        "Priya",
        "build and test internal tools for our warehouse team",
        "Python, PostgreSQL and GitHub Actions",
        27000,
        31000,
    ),
    (
        "IT Support Analyst",
        "Corby Borough Homes",
        "IT",
        "Dan",
        "look after 200 users, laptops and Microsoft 365",
        "Microsoft 365, Intune and Freshservice",
        24000,
        26500,
    ),
    (
        "Graduate Software Engineer",
        "Weldon Precision",
        "software",
        "Mark",
        "work on our production scheduling system",
        "C#, .NET and SQL Server",
        28000,
        30000,
    ),
    (
        "Junior Data Analyst",
        "Rockingham Foods",
        "insights",
        "Helen",
        "build weekly sales reports and dashboards",
        "SQL, Power BI and Excel",
        26000,
        29000,
    ),
    (
        "1st Line Service Desk Technician",
        "Kettering Health Partners",
        "service desk",
        "Sam",
        "handle tickets and phone support for clinics",
        "ServiceNow and Active Directory",
        23500,
        25000,
    ),
    (
        "Junior Web Developer",
        "Brampton Digital",
        "web",
        "Leah",
        "build and maintain client websites",
        "JavaScript, React and WordPress",
        25000,
        28000,
    ),
]


def seed(session: Session, rng: random.Random | None = None) -> int:
    rng = rng or random.Random(42)
    now = utcnow()
    session.exec(delete(Posting))
    rows: list[Posting] = []
    ext = iter(range(100000, 999999))

    def add(days_ago: int, last_seen_days_ago: int = 0, **kw) -> Posting:
        posted = now - timedelta(days=days_ago)
        p = Posting(
            external_id=str(next(ext)),
            posted_at=posted,
            first_seen=posted,
            last_seen=now - timedelta(days=last_seen_days_ago),
            times_seen=max(1, (days_ago - last_seen_days_ago) * 3),
            **kw,
        )
        rows.append(p)
        return p

    # Genuine, fresh, detailed jobs (Reed with full text).
    for title, company, team, manager, task, tools, lo, hi in GENUINE:
        desc = DETAILED.format(
            company=company,
            title=title,
            team=team,
            town="Corby",
            manager=manager,
            task=task,
            tools=tools,
        )
        add(
            rng.randint(1, 6),
            source="reed",
            title=title,
            company=company,
            location="Corby",
            description=desc,
            description_full=True,
            salary_min=lo,
            salary_max=hi,
            url="https://example.com/demo",
            applications=rng.randint(8, 45),
        )

    # Same genuine job also on Adzuna (snippet only) - must NOT count as a repost.
    add(
        3,
        source="adzuna",
        title="Junior Python Developer",
        company="Northgate Logistics",
        location="Corby, Northamptonshire",
        description=DETAILED[:180],
        salary_min=27000,
        salary_max=31000,
        url="https://example.com/demo",
    )

    # Adzuna job where the salary is Adzuna's guess.
    add(
        5,
        source="adzuna",
        title="Junior IT Technician",
        company="Stanion Facilities",
        location="Kettering",
        description="Supporting staff across three sites with hardware...",
        salary_min=24800,
        salary_max=24800,
        salary_predicted=True,
        url="https://example.com/demo",
    )

    # Classic ghost: same advert reposted every few weeks for months.
    for days in (88, 61, 33, 6):
        add(
            days,
            last_seen_days_ago=max(0, days - 27),
            source="reed",
            title="Graduate Software Developer",
            company="Apex Talent Solutions",
            location="Northampton",
            description=GHOSTY[0],
            description_full=True,
            url="https://example.com/demo",
            applications=rng.randint(250, 600),
        )

    # Evergreen "register your interest" advert, open for 2+ months.
    add(
        74,
        source="reed",
        title="Entry Level IT Roles - Register Interest",
        company="BrightPath Recruitment",
        location="Corby",
        description=GHOSTY[1],
        description_full=True,
        url="https://example.com/demo",
        applications=410,
    )

    # Agency with loads of open adverts.
    roles = [
        "Junior Developer",
        "IT Support",
        "Data Analyst",
        "Helpdesk Analyst",
        "Graduate Engineer",
        "QA Tester",
        "Junior DevOps",
        "Trainee Analyst",
        "Technical Support",
        "Junior SQL Developer",
        "Desktop Support",
        "Junior BI Analyst",
        "Service Desk Analyst",
        "IT Apprentice",
        "Junior Network Engineer",
    ]
    for role in roles:
        add(
            rng.randint(10, 40),
            source="adzuna",
            title=f"{role} - Midlands",
            company="CV Harvest Ltd",
            location="Midlands",
            description=GHOSTY[2],
            url="https://example.com/demo",
        )

    # Taken down 2 weeks ago after a normal run - shouldn't inflate anything.
    add(
        30,
        last_seen_days_ago=14,
        source="reed",
        title="Junior Software Tester",
        company="Oakley Systems",
        location="Corby",
        description=DETAILED.format(
            company="Oakley Systems",
            title="Junior Software Tester",
            team="QA",
            town="Corby",
            manager="Tom",
            task="write and run test plans",
            tools="Playwright and Jira",
        ),
        description_full=True,
        salary_min=25000,
        salary_max=27000,
        url="https://example.com/demo",
    )

    # Fresh, honest-looking adverts that just aren't for you - filtered by relevance.toml.
    not_for_you = [
        ("Senior Python Developer", "Northgate Logistics", 55000, 65000, ""),
        ("Maintenance Engineer", "Weldon Precision", 32000, 36000, ""),
        ("Junior Accountant", "Rockingham Foods", 24000, 26000, ""),
        (
            "Software Developer",
            "Brampton Digital",
            38000,
            42000,
            " You'll need 5+ years' commercial experience with C#.",
        ),
        (
            "Cyber Security Analyst",
            "Defence Systems UK",
            34000,
            40000,
            " Candidates must hold active SC clearance.",
        ),
    ]
    for title, company, lo, hi, extra in not_for_you:
        desc = DETAILED.format(
            company=company,
            title=title,
            team="the",
            town="Corby",
            manager="Alex",
            task="get stuck in",
            tools="the usual tools",
        )
        add(
            rng.randint(1, 5),
            source="reed",
            title=title,
            company=company,
            location="Corby",
            description=desc + extra,
            description_full=True,
            salary_min=lo,
            salary_max=hi,
            url="https://example.com/demo",
        )

    session.add_all(rows)
    session.commit()
    return len(rows)
