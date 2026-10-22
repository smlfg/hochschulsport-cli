"""Parser für Buchsys-Seiten und ``kurssuche.js``.

Buchsys nutzt stabile CSS-Klassen (``bs_*``). Der HTML-Parser arbeitet
ausschließlich auf diesen Klassen – nie auf „dem ersten span/div".

Wichtige Stolperfallen (live verifiziert am 2026-10-22):

* Die Kurstabelle ``table.bs_kurse`` enthält **verschachtelte** ``</tr>``
  (aus ``table.bs_tzotable``). Regex-Splitting auf ``<tr>`` zerstört die
  Zeilen → hier wird ein echter HTML-Parser benutzt.
* ``class='bs_kurse'`` und ``class="bs_kurse"`` kommen beide vor → die
  Selektoren matchen auf das Klassenattribut, nicht auf die Quotes.
* Die Kursnr ist **nicht immer numerisch** (``50100``, ``623105``,
  ``10584F``, ``o057-02``, ``14009006``).
* Preise werden je Statusgruppe als ``bs_tt1`` (Betrag) / ``bs_tt2``
  (Gruppe) geliefert; ``--`` bedeutet „kein Preis".
* Entities müssen entitisiert werden (``f&uuml;r`` → ``für``). Es wird
  ``convert_charrefs=True`` genutzt, damit Umlaute nicht verschwinden.
"""

from __future__ import annotations

import html as html_mod
import json
import re
from typing import Any, Iterable

from bs4 import BeautifulSoup

from .errors import ParseError
from .models import (
    STATUS_BY_CLASS,
    STATUS_NOT_BOOKABLE,
    Course,
    Price,
    Session,
    Sport,
)

#: Buchsys' ``sp_link()``: Entities -> ASCII, ``&`` -> `` und ``, Rest -> ``_``.
_ENTITY_MAP = {
    "&#196;": "Ae", "&#228;": "ae", "&#214;": "Oe",
    "&#246;": "oe", "&#220;": "Ue", "&#252;": "ue",
    "&amp;": "&", "&#223;": "ss",
}
_ENTITY_NUMERIC = re.compile(r"&#(\d+);")


def sp_link(name: str) -> str:
    """Buchsys-``sp_link()`` nachgebaut: Sportart -> Dateiname der Sportseite.

    Live verifiziert: die Ableitung erzeugt exakt die vorhandenen Dateinamen.
    """
    text = html_mod.unescape(name or "")
    for entity, replacement in _ENTITY_MAP.items():
        text = text.replace(entity, replacement)
    text = _ENTITY_NUMERIC.sub(lambda m: chr(int(m.group(1))), text)
    for char, replacement in (
        ("ä", "ae"),
        ("ö", "oe"),
        ("ü", "ue"),
        ("Ä", "Ae"),
        ("Ö", "Oe"),
        ("Ü", "Ue"),
        ("ß", "ss"),
    ):
        text = text.replace(char, replacement)
    text = text.replace("&", " und ")
    text = re.sub(r"_+", "_", text)
    text = re.sub(r"[^A-Za-z0-9\-]", "_", text)
    return text.lstrip("_")


def sport_filename(name: str) -> str:
    """Dateiname der Sportseite, z. B. ``_Bogensport.html``."""
    return f"_{sp_link(name)}.html"


def clean(text: str | None) -> str:
    """Text normalisieren: Entities auflösen, Whitespace kollabieren."""
    if not text:
        return ""
    value = html_mod.unescape(text)
    value = value.replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def _soup(markup: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(markup, "lxml")
    except Exception as exc:  # pragma: no cover - lxml ist Pflicht-dependency
        raise ParseError(f"HTML konnte nicht geparst werden: {exc}") from exc


def status_from_classes(classes: Iterable[str]) -> str:
    """Buchungsstatus aus den CSS-Klassen der ``bs_sbuch``-Zelle."""
    found = [c for c in classes if c in STATUS_BY_CLASS]
    if not found:
        return STATUS_NOT_BOOKABLE
    # Priorität nach STATUS_BY_CLASS-Reihenfolge (buchbar vor warteliste etc.).
    for cls, status in STATUS_BY_CLASS.items():
        if cls in found:
            return status
    return STATUS_NOT_BOOKABLE


def parse_prices(cell_text: str) -> list[Price]:
    """Preise je Statusgruppe aus einer ``bs_spreis``-Zelle (oder HTML)."""
    prices: list[Price] = []
    soup = _soup(cell_text)
    rows = soup.select("div.bs_tr")
    for row in rows:
        amount = row.select_one(".bs_tt1")
        group = row.select_one(".bs_tt2")
        if amount is None and group is None:
            continue
        group_text = clean(group.get_text()) if group else ""
        if group_text.lower().startswith("für "):
            group_text = group_text[4:].strip()
        prices.append(
            Price(
                group=group_text,
                price_eur=_parse_amount(clean(amount.get_text()) if amount else ""),
            )
        )
    if prices:
        return prices
    # Fallback: kompakte Kopfzeile wie "30/ 35/ 60/ -- euro" oder "entgeltfrei".
    flat = clean(cell_text)
    if not flat:
        return []
    lowered = flat.lower()
    if "entgeltfrei" in lowered or "free of charge" in lowered:
        return [Price(group="alle", price_eur=0.0)]
    match = re.search(r"(\d[\d.,]*)\s*(?:€|EUR|euro)", flat, re.IGNORECASE)
    if match:
        return [Price(group="", price_eur=_parse_amount(match.group(1)))]
    numbers = re.findall(r"(\d[\d.,]*)", flat)
    if numbers:
        return [Price(group="", price_eur=_parse_amount(numbers[0]))]
    return []


def _parse_amount(raw: str) -> float | None:
    """Betrag aus Text wie ``30``, ``30,00``, ``35.5``; ``--``/leer -> ``None``."""
    text = (raw or "").strip()
    if not text or text in ("--", "-", "–", "—"):
        return None
    text = re.sub(r"[^\d,.\-]", "", text).replace("-", "")
    if not text:
        return None
    # Deutsche Schreibweise: Punkt = Tausender, Komma = Dezimal.
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        value = float(text)
    except ValueError:
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def _row_status(row) -> str:
    cell = row.find("td", class_="bs_sbuch")
    if cell is None:
        return STATUS_NOT_BOOKABLE
    classes: list[str] = []
    for element in cell.find_all(class_=True):
        classes.extend(element.get("class") or [])
    return status_from_classes(classes)


def _row_detail_hex(row) -> str | None:
    """HEX-ID der Kursdetailseite (``kursinfo=<hex>``) aus der Zeile."""
    for link in row.find_all("a", href=True):
        match = re.search(r"kursinfo=([0-9A-Za-z]+)", link["href"])
        if match:
            return match.group(1)
    return None


def _row_sessions(row) -> list[Session]:
    """Termine aus der ``bs_stzo``-Zelle (verschachtelte ``bs_tzotable``)."""
    sessions: list[Session] = []
    cell = row.find("td", class_="bs_stzo")
    if cell is None:
        return sessions
    for tr in cell.select("table.bs_tzotable tr"):
        day = tr.find(class_="bs_stag")
        time = tr.find(class_="bs_szeit")
        place = tr.find(class_="bs_sort")
        sessions.append(
            Session(
                day=clean(day.get_text()) if day else None,
                time=clean(time.get_text()) if time else None,
                location=clean(place.get_text()) if place else None,
            )
        )
    return sessions


def parse_course_rows(
    markup: str, base_url: str = "", *, sport_name: str = ""
) -> list[Course]:
    """Parst alle Kurszeilen einer Buchsys-Sportseite.

    Nutzt einen echten HTML-Parser, weil die Kurstabelle verschachtelte
    ``</tr>`` enthält.
    """
    soup = _soup(markup)
    courses: list[Course] = []
    for table in soup.select("table.bs_kurse"):
        for row in table.select("tbody tr"):
            if row.find("td", class_="bs_sknr") is None:
                continue
            number_cell = row.find("td", class_="bs_sknr")
            course_nr = clean(number_cell.get_text())
            if not course_nr:
                continue
            detail_cell = row.find("td", class_="bs_sdet")
            title = ""
            period = None
            if detail_cell is not None:
                trs = [clean(div.get_text()) for div in detail_cell.select("div.bs_tr")]
                if len(trs) >= 2:
                    title = trs[1]
                elif trs:
                    title = trs[0]
                if len(trs) >= 3:
                    period = trs[2]
            period_cell = row.find("td", class_="bs_szr")
            if period_cell is not None:
                period = clean(period_cell.get_text()) or period
            instructor_cell = row.find("td", class_="bs_skl")
            instructor = (
                clean(instructor_cell.get_text()) if instructor_cell else None
            ) or None
            price_cell = row.find("td", class_="bs_spreis")
            prices = parse_prices(str(price_cell)) if price_cell else []
            sessions = _row_sessions(row)
            hex_id = _row_detail_hex(row)
            detail_url = (
                f"{base_url.rstrip('/')}/cgi/webpage.cgi?kursinfo={hex_id}"
                if hex_id and base_url
                else None
            )
            courses.append(
                Course(
                    course_nr=course_nr,
                    title=title,
                    sport=sport_name or (title.split()[0] if title else ""),
                    day=sessions[0].day if sessions else None,
                    time=sessions[0].time if sessions else None,
                    location=sessions[0].location if sessions else None,
                    instructor=instructor,
                    period=period,
                    prices=prices,
                    booking_status=_row_status(row),
                    detail_url=detail_url,
                    sessions=sessions,
                )
            )
    return courses


def parse_sports(markup: str) -> list[Sport]:
    """Sportarten aus der Angebotsübersicht (``index.html``).

    Die Links der Übersicht liegen in ``<dl class="bs_menu">``; der
    Dateiname folgt den Buchsys-``sp_link()``-Regeln.
    """
    soup = _soup(markup)
    sports: list[Sport] = []
    seen: set[str] = set()
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if not href.startswith("_") or not href.endswith(".html"):
            continue
        name = clean(link.get_text())
        if not name or name in seen:
            continue
        seen.add(name)
        sports.append(Sport(name=name, slug=href))
    return sports


def parse_search_data(js_text: str) -> dict[str, Any]:
    """Parst ``kurssuche.js`` (``const data={…};``) als JSON-Dict."""
    match = re.match(r"\s*const\s+data\s*=\s*(\{.*\})\s*;?\s*$", js_text, re.S)
    if not match:
        raise ParseError(
            "kurssuche.js hat ein unerwartetes Format (kein 'const data={…};')."
        )
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise ParseError(f"kurssuche.js ist kein gültiges JSON: {exc}") from exc
    if not isinstance(data, dict) or "kurse" not in data:
        raise ParseError("kurssuche.js enthält keinen 'kurse'-Bereich.")
    return data


def courses_from_search_data(data: dict[str, Any], base_url: str = "") -> list[Course]:
    """Baut Kurse aus dem JSON von ``kurssuche.js``.

    Feldindizes (live verifiziert, identisch auf allen Portalen):
    0 Typ, 1 Kursnr, 2 Sportart, 3 Titel, 4 Tages-Indizes, 5 Zeiten,
    6 Ort-Indizes, 7 Zeitraum, 8 Leitung, 9 Preis-HTML, 10 buchbar-Flag,
    11 Timestamp, 12 Bereichs-Index, 13-15 ungenutzt, 16 Merkmale.
    """
    days = data.get("tage") or []
    places = data.get("orte") or []
    areas = data.get("bereiche") or []
    courses: list[Course] = []
    for raw in data.get("kurse") or []:
        if not isinstance(raw, list) or len(raw) < 13:
            continue
        course_nr = str(raw[1])
        sport = clean(raw[2])
        title_part = clean(raw[3])
        day = None
        time = None
        location = None
        day_indexes = raw[4] or []
        times = raw[5] or []
        place_indexes = raw[6] or []
        for slot in range(min(5, len(day_indexes), len(times))):
            idx = day_indexes[slot]
            if not idx:
                continue
            if day is None and isinstance(idx, int) and idx < len(days):
                day = clean(days[idx][0])
            if time is None:
                time = clean(times[slot]) or None
            if location is None:
                pidx = place_indexes[slot] if slot < len(place_indexes) else 0
                if isinstance(pidx, int) and 0 < pidx < len(places):
                    location = clean(places[pidx][0])
        prices = parse_prices(str(raw[9])) if raw[9] else []
        category = None
        area_idx = raw[12]
        if isinstance(area_idx, int) and 0 <= area_idx < len(areas):
            category = clean(areas[area_idx]) or None
        bookable_flag = raw[10] if len(raw) > 10 else 0
        status = (
            "buchbar"
            if isinstance(bookable_flag, int) and bookable_flag == 1
            else STATUS_NOT_BOOKABLE
        )
        courses.append(
            Course(
                course_nr=course_nr,
                title=f"{sport} {title_part}".strip(),
                sport=sport,
                day=day,
                time=time,
                location=location,
                instructor=clean(raw[8]) or None,
                period=clean(raw[7]) or None,
                prices=prices,
                booking_status=status,
                detail_url=None,
                category=category,
            )
        )
    return courses


_DETAIL_LABELS = frozenset(
    {
        "Zeitraum:",
        "Leitung:",
        "Veranstaltungsorte:",
        "Preise:",
        "geplante Termine:",
        "Angebotsdetails",
    }
)


def _text_after_label(tag) -> str:
    parts: list[str] = []
    for sibling in tag.next_siblings:
        name = getattr(sibling, "name", None)
        if name == "b":
            break
        if name == "table":
            break
        if name == "br":
            continue
        if hasattr(sibling, "get_text"):
            chunk = clean(sibling.get_text(" ", strip=True))
            if chunk:
                parts.append(chunk)
        elif isinstance(sibling, str):
            chunk = clean(sibling)
            if chunk:
                parts.append(chunk)
    return clean(" ".join(parts))


def parse_sport_description(markup: str) -> str | None:
    """Beschreibungstext der Sportseite (``div.bs_kursbeschreibung``)."""
    soup = _soup(markup)
    blocks = soup.select("div.bs_kursbeschreibung")
    if not blocks:
        return None
    texts = [clean(block.get_text("\n", strip=True)) for block in blocks]
    joined = clean("\n\n".join(t for t in texts if t))
    return joined or None


def parse_course_detail(
    markup: str,
    base_url: str = "",
    *,
    detail_url: str | None = None,
) -> Course | None:
    """Parst eine Kursdetailseite (``cgi/webpage.cgi?kursinfo=<hex>``)."""
    soup = _soup(markup)
    content = soup.find(id="bs_content")
    if content is None:
        return None
    number = None
    title = ""
    period = None
    instructor = None
    locations: list[dict[str, Any]] = []
    prices: list[Price] = []
    sessions: list[Session] = []

    for strong in content.find_all("b"):
        label = clean(strong.get_text())
        if (
            label.endswith(":")
            and label not in _DETAIL_LABELS
            and re.fullmatch(r"[A-Za-z0-9\-]+:", label)
        ):
            number = label.rstrip(":")
            continue
        if label == "Zeitraum:":
            period = _text_after_label(strong) or None
        elif label == "Leitung:":
            instructor = _text_after_label(strong) or None
        elif label == "Veranstaltungsorte:":
            text_block = strong.find_next("div", class_="bs_text")
            if text_block is not None:
                raw = clean(text_block.get_text(" ", strip=True))
                if raw:
                    name = raw.split(",")[0].strip()
                    address = raw
                    if "," in raw:
                        address = clean(raw.split(",", 1)[1])
                    locations.append({"name": name, "address": address})
            else:
                text = _text_after_label(strong)
                if text:
                    locations.append({"name": text})
        elif label == "Preise:":
            text = _text_after_label(strong)
            for line in text.split("\n"):
                line = clean(line)
                if not line:
                    continue
                match = re.match(
                    r"([\d.,]+)\s*EUR\s*(?:für|fuer)?\s*(.+)", line, re.IGNORECASE
                )
                if match:
                    prices.append(
                        Price(
                            group=clean(match.group(2)),
                            price_eur=_parse_amount(match.group(1)),
                        )
                    )
            if not prices and "entgeltfrei" in text.lower():
                prices = [Price(group="alle", price_eur=0.0)]

    for table in content.select("table.bs_kurse, table"):
        for tr in table.select("tr"):
            cells = tr.find_all("td")
            if not cells or not cells[0].get("data-label"):
                continue
            session = Session()
            for td in cells:
                label = clean(td.get("data-label"))
                value = clean(td.get_text())
                if label == "Tag":
                    session.day = value
                elif label == "Termin":
                    session.date = value.replace("Termin", "").strip() or value
                elif label == "Zeit":
                    session.time = value
                elif label == "Ort":
                    session.location = value
            if session.day or session.date:
                sessions.append(session)

    heads = [clean(h.get_text()) for h in content.select("div.bs_head")]
    for head in heads:
        if head and head not in {"Angebotsdetails"} and not head.endswith(":"):
            title = head
            break

    if number is None:
        return None
    resolved_url = detail_url
    if resolved_url is None and base_url:
        resolved_url = f"{base_url.rstrip('/')}/cgi/webpage.cgi?kursinfo="
    return Course(
        course_nr=number,
        title=title,
        sport=title.split()[0] if title else "",
        day=sessions[0].day if sessions else None,
        time=sessions[0].time if sessions else None,
        location=sessions[0].location if sessions else None,
        instructor=instructor,
        period=period,
        prices=prices,
        booking_status=STATUS_NOT_BOOKABLE,
        detail_url=resolved_url,
        sessions=sessions,
        locations=locations,
    )
