# UX-Spec – `hsport`

Diese Spec beschreibt die **gewünschte** Bedienung aus Sicht eines Menschen. Sie ist
vor der Umsetzung geschrieben und bewusst unabhängig von einzelnen Parser-Details.
Live erkundet wurde am 2026-10-30 das Stuttgarter Buchsys-Portal (Volleyball,
Kurs 32304). Der erste Buchungsschritt (`BS_Kursid_31584` auf der Sportseite)
wurde genau einmal per POST ausgelöst. Das Portal antwortete wegen des
passwortgeschützten Kurses mit einer Weiterleitung zur CMS-Anmeldung; die
Personendaten- und Bestätigungsseiten sind deshalb als **synthetisch** markiert.

## Meta

```ux-meta
{
  "tool": "hsport",
  "install": "pipx install git+https://github.com/smlfg/hochschulsport-cli",
  "base_url_env": "HS_BASE_URL",
  "credential_env": [
    "HS_LOGIN_USER",
    "HS_LOGIN_PASSWORD",
    "HS_STATUSGRUPPE",
    "HSPORT_FIRSTNAME",
    "HSPORT_LASTNAME",
    "HS_BOOKING_EMAIL"
  ]
}
```

`HS_BASE_URL` ist die vom Code gelesene Basis-URL (Alias: `HS_PORTAL`). Wichtig:
`resolve_portal()` normalisiert URLs und entfernt dabei den Port; ein Fake-Server
auf `127.0.0.1:<port>` ist mit dem aktuellen Stand **nicht** erreichbar. Das ist
ein CLI-Befund, kein Bestandteil der gewünschten Bedienung (siehe
`scratch/REPORT-C1.md`).

## Sitzung 1 – Installation und interaktiver Login

Der Mensch installiert einmalig und legt danach seine Zugangsdaten und
Personendaten für das aktuelle Portal ab. Die Prompts entsprechen den real
vorhandenen Texten der CLI. Neben Login, Passwort, Vorname, Nachname und
Statusgruppe fragt `login` die E-Mail für Buchungen ab; wenn der Login wie eine
E-Mail-Adresse aussieht, ist er der Default und Enter übernimmt ihn.

```ux-session
$ pipx install git+https://github.com/smlfg/hochschulsport-cli
$ hsport login
<~ Login für .+
< E-Mail/Login
> max.beispiel@example.org
< Passwort:
> geheim
< Vorname:
> Max
< Nachname:
> Beispiel
< Statusgruppe:
< Auswahl [1]:
> 1
< E-Mail für Buchungen [max.beispiel@example.org]:
>
<~ Login für .+ gespeichert\.
! exit 0
```

## Sitzung 2 – Kurse per Name suchen

Die Suche nach dem Sportnamen ist der einfachste Einstieg. Zusätzlich zeigt
`--query` die Treffer aus dem Suchindex `kurssuche.js`. Beide Wege liefern den
buchbaren Volleyball-Kurs 32304.

```ux-session
$ hsport courses volleyball
< Kurse (10)
< 32304: Volleyball LS3 hohes Spielniveau / Advanced
< buchbar
$ hsport courses --query volleyball
< Kurse (
< 32304: Volleyball LS3 hohes Spielniveau / Advanced
< buchbar
! exit 0
```

## Sitzung 3 – Buchung bis zur verbindlichen Bestätigung

Der Mensch sieht den gefundenen buchbaren Kurs, prüft die Zusammenfassung und
bestätigt erst danach verbindlich. Gibt es genau einen buchbaren Treffer, wählt
die CLI ihn direkt aus und weist auf die übrigen (nicht buchbaren) Treffer hin;
bei mehreren Treffern folgt zusätzlich eine Nummernabfrage. Nach `j` werden alle
Formularschritte bis zur endgültigen Buchung gesendet; erst danach erscheint die
Erfolgsmeldung. Bei `N` wird kein Formularschritt gesendet.

```ux-session
$ hsport book volleyball
< 1 buchbarer Kurs
< Kurs: 32304 Volleyball LS3 hohes Spielniveau / Advanced
< Tag: Mi
< Zeit: 19:30-21:30
< Ort: Sporthalle Allmandring
< Preis: 45,00 € (Studierende)
< Name: Max Beispiel
< Statusgruppe: Studierende
< [j/N]
> j
< Buchung bestätigt.
! exit 0
```

## Sitzung 4 – Default-Portal wechseln (optional)

Der Schnellstart der README zeigt zusätzlich den Portalwechsel. Der Befehl
speichert nur die Auswahl und macht keinen Netzwerkzugriff.

```ux-session
$ hsport config portal hamburg
< Default-Portal: hamburg (Universität Hamburg)
! exit 0
```

## Lesende Routen des Fake-Servers

```ux-routes
[
  {
    "method": "GET",
    "path": "/angebote/aktueller_zeitraum/index.html",
    "response": "tests/fixtures/ux/index.html",
    "status": 200,
    "content_type": "text/html; charset=utf-8"
  },
  {
    "method": "GET",
    "path": "/angebote/aktueller_zeitraum/kurssuche.js",
    "response": "tests/fixtures/ux/kurssuche.js",
    "status": 200,
    "content_type": "text/javascript; charset=utf-8"
  },
  {
    "method": "GET",
    "path": "/angebote/aktueller_zeitraum/_Volleyball.html",
    "response": "tests/fixtures/ux/volleyball.html",
    "status": 200,
    "content_type": "text/html; charset=utf-8"
  }
]
```

## Schreibende Schritte bis zur verbindlichen Buchung

Schritt 1 ist der live beobachtete „buchen“-Button der Sportseite. Das Portal
verlangt für diesen Kurs zusätzlich eine CMS-Anmeldung; die zurückgegebene
Personendaten-Seite ist daher im Fixture nachgebaut. Die Schritte 2 und 3 sind
aus dem bekannten Buchsys-Ablauf abgeleitet und als `synthetisch` markiert.
Keiner der Schritte wird vor der `[j/N]`-Bestätigung gesendet.

```ux-formsteps
[
  {
    "id": "kurs_waehlen",
    "method": "POST",
    "path": "/cgi/anmeldung.fcgi",
    "sends": ["BS_Kursid_*"],
    "response": "tests/fixtures/ux/step1_formular.html",
    "before_confirm": false,
    "live": "erkundet"
  },
  {
    "id": "daten",
    "method": "POST",
    "path": "/cgi/anmeldung.fcgi",
    "sends": ["statusorig", "vorname", "name", "email", "tnbed"],
    "response": "tests/fixtures/ux/step2_uebersicht.html",
    "before_confirm": false,
    "live": "synthetisch"
  },
  {
    "id": "verbindlich",
    "method": "POST",
    "path": "/cgi/anmeldung.fcgi",
    "sends": ["fid"],
    "response": "tests/fixtures/ux/step3_bestaetigt.html",
    "final": true,
    "before_confirm": false,
    "live": "synthetisch"
  }
]
```
