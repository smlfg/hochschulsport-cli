"""Parser-Tests gegen gespeicherte Buchsys-Fixtures."""

from __future__ import annotations

from pathlib import Path

from hochschulsport_cli.errors import ParseError
from hochschulsport_cli.parser import (
    courses_from_search_data,
    parse_course_detail,
    parse_course_rows,
    parse_search_data,
    parse_sports,
    sport_filename,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_bytes().decode("latin-1")


def test_sp_link_umlaut():
    assert sport_filename("Yoga für alle") == "_Yoga_fuer_alle.html"


def test_parse_sports_stuttgart_count():
    sports = parse_sports(_read("index_stuttgart.html"))
    assert len(sports) == 168
    assert all(s.slug.endswith(".html") and s.slug.startswith("_") for s in sports)


def test_parse_bogensport_rows_status_and_prices():
    courses = parse_course_rows(
        _read("sport_bogensport_stuttgart.html"),
        "https://example.com",
        sport_name="Bogensport",
    )
    assert len(courses) == 3
    by_nr = {c.course_nr: c for c in courses}
    assert by_nr["50100"].booking_status == "buchbar"
    assert by_nr["50101"].booking_status == "noch_nicht_buchbar"
    assert by_nr["50102"].booking_status == "warteliste"
    assert by_nr["50100"].day == "Sa"
    assert by_nr["50100"].time == "12:00-15:00"
    assert by_nr["50100"].location == "Außenanlage Allmandring"
    assert by_nr["50100"].title == "Bogensport für Fortgeschrittene"
    assert by_nr["50100"].instructor == "Bernd Ritzinger, Thomas Bayerlein"
    prices = by_nr["50100"].prices
    assert [p.group for p in prices] == ["Studierende", "Beschäftigte", "Externe"]
    assert [p.price_eur for p in prices] == [30.0, 35.0, 60.0]
    assert by_nr["50101"].prices[0].price_eur == 0.0


def test_kurssuche_js_loads():
    js = (FIXTURES / "kurssuche_stuttgart.js").read_text(encoding="utf-8", errors="replace")
    data = parse_search_data(js)
    courses = courses_from_search_data(data)
    assert len(courses) == 404


def test_parse_course_detail_13600_prices():
    course = parse_course_detail(
        _read("course_13600_stuttgart.html"),
        "https://anmeldung.hochschulsport.uni-stuttgart.de",
        detail_url="https://anmeldung.hochschulsport.uni-stuttgart.de/cgi/webpage.cgi?kursinfo=76DC9CFAE3",
    )
    assert course is not None
    assert course.course_nr == "13600"
    assert [p.group for p in course.prices] == [
        "Studierende",
        "Beschäftigte",
        "Externe",
    ]
    assert [p.price_eur for p in course.prices] == [15.0, 20.0, 30.0]


def test_parse_course_detail_50100():
    course = parse_course_detail(
        _read("course_50100_stuttgart.html"),
        "https://anmeldung.hochschulsport.uni-stuttgart.de",
        detail_url="https://anmeldung.hochschulsport.uni-stuttgart.de/cgi/webpage.cgi?kursinfo=76DC115FEF",
    )
    assert course is not None
    assert course.course_nr == "50100"
    assert course.title == "Bogensport für Fortgeschrittene"
    assert course.period == "17.10.2026-10.04.2027"
    assert len(course.sessions) >= 1
    assert course.locations[0]["name"].startswith("Außenanlage")


def test_kurssuche_invalid_raises():
    try:
        parse_search_data("not json")
    except ParseError as exc:
        assert exc.kind == "parse"
    else:
        raise AssertionError("expected ParseError")
