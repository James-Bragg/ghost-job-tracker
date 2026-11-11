import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlmodel import create_engine

from ghostjobs.db import Posting, get_session, init_db
from ghostjobs.skills import extract, format_report, load_skills, report, role_family

SKILLS = load_skills(str(Path(__file__).parent.parent / "skills.toml"))
NOW = datetime(2026, 11, 11, tzinfo=UTC)


def found(text):
    return set(extract(text, SKILLS))


def test_basic_matches():
    f = found("<p>Experience with C#, .NET and SQL Server. Python a bonus. Git, Docker, AWS.</p>")
    assert {"C#", ".NET", "SQL Server", "Python", "Git", "Docker", "AWS"} <= f


def test_no_false_friends():
    f = found(
        "We react quickly, excel at service, and enjoy spring and the rest of the day. "
        "JavaScript is not Java."
    )
    assert "React" not in f and "Excel" not in f and "Spring" not in f
    assert "JavaScript" in f


def test_java_whole_word():
    assert "Java" in found("Java developer")
    assert "Java" not in found("JavaScript developer")


def test_case_sensitive_aliases():
    assert "React" in found("Building UIs in React and TypeScript")
    assert "Excel" in found("Advanced Excel skills")


def test_support_skills():
    f = found(
        "1st line support: Active Directory, Microsoft 365, DNS/DHCP, ServiceNow, ITIL, "
        "CompTIA A+ desirable, full UK driving licence"
    )
    assert {
        "Active Directory",
        "Microsoft 365",
        "Networking basics",
        "Ticketing systems",
        "ITIL",
        "CompTIA A+",
        "Driving licence",
    } <= f


@pytest.mark.parametrize(
    "title,fam",
    [
        ("Junior Python Developer", "development"),
        ("IT Support Analyst", "support"),
        ("1st Line Service Desk Technician", "support"),
        ("Junior Data Analyst", "data"),
        ("Software Tester", "testing"),
        ("Junior Network Engineer", "infrastructure"),
        ("Cyber Security Analyst", "security"),
        ("Graduate Software Engineer", "development"),
    ],
)
def test_role_family(title, fam):
    assert role_family(title) == fam


def test_report_counts_relevant_recent_unique_jobs():
    engine = create_engine("sqlite://")
    init_db(engine)
    with get_session(engine) as s:

        def add(i, title, skills, relevant=True, days_ago=1, company="Acme", source="reed"):
            s.add(
                Posting(
                    source=source,
                    external_id=str(i),
                    title=title,
                    company=company,
                    relevant=relevant,
                    skills=json.dumps(skills),
                    first_seen=NOW - timedelta(days=days_ago),
                )
            )

        add(1, "Junior Developer", ["Python", "Git"])
        add(2, "Junior Developer", ["Python", "Git"], source="adzuna")  # same job, other board
        add(3, "IT Support Analyst", ["Microsoft 365", "Active Directory"], company="B")
        add(4, "IT Technician", ["Microsoft 365"], company="C")
        add(5, "Service Desk Analyst", ["Microsoft 365", "ITIL"], company="D")
        add(6, "Senior Developer", ["Kubernetes"], relevant=False, company="E")
        add(7, "Junior Developer", ["COBOL"], days_ago=90, company="F")
        s.commit()
        r = report(s, days=30, now=NOW)
    assert r.total == 4
    assert dict(r.overall)["Microsoft 365"] == 3
    assert "Kubernetes" not in dict(r.overall) and "COBOL" not in dict(r.overall)
    assert r.by_family["support"][0] == 3
    text = format_report(r)
    assert "75%  Microsoft 365" in text
    assert "Support (3 jobs)" in text
