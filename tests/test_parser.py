"""Parser-Tests gegen gespeicherte Buchsys-Fixtures."""

from __future__ import annotations

from pathlib import Path

from hochschulsport_cli.errors import ParseError
from hochschulsport_cli.parser import (
    courses_from_search_data,
    parse_course_rows,
    parse_search_data,
    parse_sports,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_bytes().decode("latin-1")


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


def test_kurssuche_invalid_raises():
    try:
        parse_search_data("not json")
    except ParseError as exc:
        assert exc.kind == "parse"
    else:
        raise AssertionError("expected ParseError")
