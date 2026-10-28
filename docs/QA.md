# QA – hochschulsport-cli (`hsport`)

Live-QA am 2026-10-28 gegen das Default-Portal **stuttgart**. Getestet wurde ein frischer venv mit
`pip install git+https://github.com/smlfg/hochschulsport-cli`. Es gab nur lesende Aufrufe:
kein `book` außer `book --help`, kein `--confirm`, kein Login und mindestens 2 s zwischen Requests.
Worker war opencode (`deepseek-v4.1-flash-free`). Insgesamt liefen drei QA-Runden, nach jeder Runde wurden die gefundenen Bugs gefixt.

## Live geprüft (Runde 3, Stand `4ad8495`)

| Befehl | Exit | Ergebnis |
|---|---:|---|
| `hsport --version` / `--help` | 0 | OK |
| `hsport portals --json` | 0 | OK: 7 Portale, gültiges JSON |
| `hsport sports --query yoga --json` | 0 | OK: alle Treffer enthalten „yoga“, Summe `course_count` 12 = Kurse |
| `hsport courses --sport yoga --json` | 0 | OK: 12 Kurse, `period` ohne HTML, `detail_url` gesetzt |
| `hsport courses yoga --day Mo --json` | 0 | OK: nur Montag |
| `hsport courses yoga --free-only --json` | 0 | OK: nur `buchbar` |
| `hsport courses "Acro Yoga & Bodenakrobatik" --json` | 0 | OK: Sonderzeichen-Sportart |
| `hsport course <kursnr> --json` | 0 | OK: Preise, Termine, Ort plausibel, Wochentage stimmen |
| `hsport watch <kursnr> --state-file … --json` | 0 | OK: State-Datei geschrieben |
| `hsport course 99999999 --json` | 1 | OK: JSON-Fehler `usage`, kein Traceback |
| `hsport --portal https://invalid.example --json sports` | 3 | OK: JSON-Fehler `network` |
| `hsport courses` / `hsport nope` / `hsport --json courses --day` | 1 | OK: `usage` |
| `hsport courses xyzquatsch --json` | 1 | OK: `usage` mit Hinweis auf `sports --query` |
| `hsport book --help` | 0 | OK: es wird nichts gebucht |

## In dieser QA gefixt

| Befund | Fix |
|---|---|
| `--version` und `--help` endeten mit Exit 2 | `97afe6b`, Test `4c35612` |
| argparse-Fehler gaben Exit 2 (Auth) statt 1 (Usage) zurück | `f210042`, Test `87e866f` |
| `courses --sport/--query`: `period` enthielt `<wbr />`, `detail_url` war null, der Status kam verlustbehaftet aus dem Suchindex | `73bad77`, Test `fdc48eb` |
| Ein nicht exakter positionaler Sportname (`courses yoga`) lief in HTTP 404 und wurde als `parse` gemeldet (Exit 4) | `39435df`, Test `a7509a2` |
| `sports`: `course_count` war 0 bei Namen mit HTML-Entities wie `&` | `7e16013`, Test `4ad8495` |

## Offen

- **`sports.course_count` ist für einige Sportarten 0, obwohl die Sportseite Kurse hat.** Beispiele sind Wandern, Queerobic und Improvisation & Schauspiel. Die Ursache ist eine Datenlücke im Portal: Der Suchindex `kurssuche.js` enthält diese Sportarten gar nicht. Mögliche Lösung: `null` („unbekannt“) statt 0 ausgeben oder die Sportseite zählen.
- **`courses --sport/--query` lädt zur Anreicherung jede passende Sportseite.** Dafür gibt es keinen Request-Abstand im HTTP-Client, bei `yoga` sind das rund 10 Requests in etwa 3 s.
- **Kosmetik:** JSON-Fehlerobjekte stehen auf stderr. `course` liefert `18:00- 19:30`, `courses` dagegen `18:00-19:30`.
