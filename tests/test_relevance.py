from pathlib import Path

import pytest

from ghostjobs.db import Posting
from ghostjobs.relevance import check, check_title, load_rules

RULES = load_rules(str(Path(__file__).parent.parent / "relevance.toml"))


@pytest.mark.parametrize(
    "title",
    [
        "Junior Python Developer",
        "IT Support Analyst",
        "1st Line Service Desk Technician",
        "Graduate Software Engineer",
        "Junior Data Analyst",
        "C# Developer",
        ".NET Developer",
        "IT Apprentice",
        "QA Tester",
    ],
)
def test_relevant_titles(title):
    assert check_title(title, RULES)[0], title


@pytest.mark.parametrize(
    "title",
    [
        "Senior Python Developer",
        "Sr. Software Engineer",
        "Lead Developer",
        "IT Manager",
        "Maintenance Engineer",
        "Junior Accountant",
        "Recruitment Consultant - IT",
        "Warehouse Operative",
        "Digital Marketing Executive",
    ],
)
def test_irrelevant_titles(title):
    assert not check_title(title, RULES)[0], title


def P(**kw):
    base = dict(source="reed", external_id="1", title="Junior Developer", company="Acme")
    base.update(kw)
    return Posting(**base)


def test_years_of_experience():
    assert not check(P(description="Requires 3+ years' commercial experience in Python"), RULES)[0]
    assert not check(P(description="<li>5 years of professional software experience</li>"), RULES)[
        0
    ]
    assert check(P(description="1-2 years experience is a bonus but not essential"), RULES)[0]
    assert check(P(description="Founded 10 years ago, we're a friendly team"), RULES)[0]


def test_clearance_excluded():
    ok, why = check(P(description="Must hold SC clearance to start"), RULES)
    assert not ok and "sc" in why.lower()


def test_no_rules_file_means_everything_relevant(tmp_path):
    rules = load_rules(str(tmp_path / "nope.toml"))
    assert check(P(title="Senior Chef"), rules)[0]
