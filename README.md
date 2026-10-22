# hochschulsport-cli

Agent-CLI für Hochschulsport-Buchungsportale (Buchsys): Sportarten, Kurse,
Kursdetails, Buchungsstatus-Watch und Buchungs-Vorbereitung. **Buchen nur mit
`--confirm`.**

## Installation

```bash
pip install git+https://github.com/smlfg/hochschulsport-cli
# oder lokal:
pip install .
```

Console-Script: `hsport`

## Globale Optionen

| Option | Beschreibung |
|--------|----------------|
| `--json` | Erfolg: ein JSON-Objekt auf stdout; Fehler: JSON auf stderr |
| `--portal URL` | Basis-URL oder Kurz-ID (`stuttgart`, `buchsys.de/bremen`, …) |
| `--timeout SEK` | HTTP-Timeout (Default: 20) |

Umgebung: `HS_PORTAL` / `HS_BASE_URL` (Default-Portal), `XDG_CONFIG_HOME`.

## Portale

`hsport portals [--json]` – sieben bekannte Portale (Default: **stuttgart**).

```bash
hsport portals --json
hsport sports --query yoga --json
hsport courses Bogensport --day Mo --free-only --json
hsport courses --sport yoga --json
hsport courses --query "Schwimmen" --sport schwimm --json
```

`courses` verlangt einen **positionalen Sportnamen** (exakte Sportseite), `--sport`
(Substring-Filter auf die Sportart, case-insensitive) oder `--query`. Positionaler
Sportname und `--query` schließen sich aus; `--sport` lässt sich mit `--query` kombinieren.

## `hsport course <kursnr>`

Live-Details: Sport, Titel, Termine, Orte, Zeitraum, Leitung, Preise,
Buchungsstatus, Detail-URL, Beschreibung der Sportseite.

```bash
hsport course 50100 --json
```

Unbekannte Kursnummer → Exit **1** (`usage`), JSON-Fehlerobjekt mit `--json`.

## `hsport watch <kursnr> [--state-file PATH]`

Speichert den letzten Buchungsstatus unter
`$XDG_CONFIG_HOME/hochschulsport-cli/watch.json` (Rechte **0600**). Meldet
Änderungen (`changed: true`, `previous_status`).

| Exit | Bedeutung |
|------|-----------|
| 0 | Kein Statuswechsel |
| 2 | Status hat sich geändert |
| 1 | Ungültige/defekte State-Datei, unbekannter Kurs, … |

```bash
hsport watch 50100 --json
hsport watch 50100 --state-file /tmp/hs-watch.json --json
```

## `hsport book <kursnr> [--confirm]`

**Ohne `--confirm`:** Trockenlauf – Kurs, Status, Preise, Formular (Action,
Felder inkl. `BS_Code` / `BS_Kursid_*`), keine POST-Anfrage.

**Mit `--confirm`:** Absenden nur nach gesetzten Umgebungsvariablen (sonst Exit
**1**, **kein** Request):

| Variable | Pflicht | Beschreibung |
|----------|---------|----------------|
| `HS_LOGIN_USER` oder `HSPORT_LOGIN_USER` | ja | Portal-Login |
| `HS_LOGIN_PASSWORD` oder `HSPORT_LOGIN_PASSWORD` | ja | Passwort (nur Env) |
| `HS_STATUSGRUPPE` oder `HSPORT_STATUSGRUPPE` | ja | z. B. `Studierende` |
| `HSPORT_FIRSTNAME` | ja | Vorname |
| `HSPORT_LASTNAME` | ja | Nachname |
| `HS_BOOKING_EMAIL` / `HSPORT_EMAIL` | optional | falls Portal verlangt |
| `HS_SESSION_FILE` | optional | Cookie-Datei (0600) |

```bash
hsport book 50100 --json
# Nur mit bewusst gesetzten Env und --confirm:
export HS_LOGIN_USER=… HS_LOGIN_PASSWORD=… HS_STATUSGRUPPE=Studierende \
  HSPORT_FIRSTNAME=… HSPORT_LASTNAME=…
hsport book 50100 --confirm --json
```

Kurs nicht buchbar → Exit **5** (`forbidden`).

### Sicherheit

Passwörter nie als CLI-Flags. `--confirm` ohne vollständige Env sendet nichts.
Sessions nur OS-Schlüsselbund oder Datei mit 0600, nie im Repo.

## Exit-Codes (alle Befehle)

| Code | `kind` | Bedeutung |
|------|--------|-----------|
| 0 | – | Erfolg |
| 1 | `usage` | Validierung, unbekannter Kurs, fehlende Env |
| 2 | `auth` / Watch: geändert | Login / Watch-Statuswechsel |
| 3 | `network` | Netzwerk, HTTP ≥ 500 |
| 4 | `parse` | HTML/JSON unlesbar |
| 5 | `forbidden` | Nicht buchbar, Aktion gesperrt |

JSON-Fehler:

```json
{"error": {"code": 1, "kind": "usage", "message": "…", "portal": "stuttgart"}}
```

## Tests

```bash
pip install -e ".[dev]"
pytest
```

Tests nutzen Fixtures unter `tests/fixtures/` und den Netzwerk-Harness
(`tests/harness/sitecustomize.py`, `leak_check.py`) – **kein** Zugriff auf
echte Server.

## Lizenz

MIT – siehe [LICENSE](LICENSE).
