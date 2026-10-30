# hochschulsport-cli

## Schnellstart (für Menschen)

```bash
pipx install git+https://github.com/smlfg/hochschulsport-cli
hsport login
hsport book volleyball
hsport config portal hamburg
```

Alternative: `pip install --user git+https://github.com/smlfg/hochschulsport-cli`.
Wenn der Befehl danach nicht gefunden wird: pipx nutzen oder das bin-Verzeichnis des venv in den PATH aufnehmen. `hsport: command not found` nach pip install? Das bin-Verzeichnis des venv liegt nicht im PATH (z. B. bei aktivem conda base). Lösung: pipx, oder `export PATH="$HOME/venvs/global/bin:$PATH"` bzw. Pfad aus `pip show -f hochschulsport-cli`.

## Für Agenten

Umgebungsvariablen: `HS_LOGIN_USER`, `HS_LOGIN_PASSWORD`, `HS_STATUSGRUPPE`, `HSPORT_FIRSTNAME`, `HSPORT_LASTNAME`, `HS_PORTAL`. Env überschreibt die Config. Buchen nur mit `hsport book <kursnr> --confirm` (oder `--yes`); mit `--json` bleibt die Maschinenausgabe stabil.

Agent-CLI für Hochschulsport-Buchungsportale (Buchsys): Sportarten, Kurse,
Kursdetails, Buchungsstatus-Watch und Buchung. **Im Terminal fragt `hsport book`
vor dem Buchen nach; Agenten buchen nur mit `--confirm`/`--yes`.**

## Installation

Empfohlen (landet im PATH):

```bash
pipx install git+https://github.com/smlfg/hochschulsport-cli
```

Mit pip (dann muss das `bin`-Verzeichnis des venv im PATH liegen):

```bash
pip install git+https://github.com/smlfg/hochschulsport-cli
```

Aus einem lokalen Klon (im Repo-Ordner): `pip install .`

Console-Script: `hsport`

## Globale Optionen

| Option | Beschreibung |
|--------|----------------|
| `--json` | Erfolg: ein JSON-Objekt auf stdout; Fehler: JSON auf stderr |
| `--portal URL` | Basis-URL oder Kurz-ID (`stuttgart`, `buchsys.de/bremen`, …) |
| `--timeout SEK` | HTTP-Timeout (Default: 20) |

Umgebung: `HS_PORTAL` / `HS_BASE_URL` (Default-Portal), `XDG_CONFIG_HOME`.

## Befehle

| Befehl | Zweck |
|--------|-------|
| `hsport portals` | Bekannte Portale, aktueller Default und dessen Quelle |
| `hsport login` / `hsport logout` | Login interaktiv speichern / löschen |
| `hsport whoami` | Gespeicherte Identität anzeigen (Passwort nur als Status) |
| `hsport config` / `hsport config portal <id>` | Konfiguration anzeigen / Default-Portal setzen |
| `hsport sports`, `hsport courses`, `hsport course <kursnr>` | Sportarten und Kurse |
| `hsport watch <kursnr>` | Buchungsstatus beobachten |
| `hsport book <kursnr\|sport>` | Trockenlauf oder mit `--confirm` / `--yes` buchen |

## Portale

`hsport portals [--json]` – sieben bekannte Portale (Default: **stuttgart**).

```bash
hsport portals --json
hsport sports --query yoga --json
hsport courses Bogensport --day Mo --free-only --json
hsport courses --sport yoga --json
hsport courses --query "Schwimmen" --sport schwimm --json
```

`courses` verlangt einen **positionalen Sportnamen**, `--sport` (Substring-Filter auf
die Sportart, case-insensitive) oder `--query`. Der positionale Name wird
case-insensitiv gegen die Sportartenliste aufgelöst (exakter Name bevorzugt, sonst
werden passende Sportseiten geladen). Kein Treffer → Exit **1** (`usage`) mit Hinweis
auf `hsport sports --query` und `--sport`. Positionaler Sportname und `--query`
schließen sich aus; `--sport` lässt sich mit `--query` kombinieren.

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

Auch argparse-Fehler (unbekannter Befehl, fehlende/ungültige Argumente) liefern
Exit **1** (`usage`), mit und ohne `--json`. `--help` und `--version` bleiben Exit 0.

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
