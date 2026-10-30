# UX-Fixtures – Herkunft und Bereinigung

Live erkundet am 2026-10-30 gegen das Stuttgarter Buchsys-Portal
(`https://anmeldung.hochschulsport.uni-stuttgart.de`). Es wurden nur GETs
gemacht, plus **genau ein** POST des ersten Buchungsschritts.

## Live

- `index.html` – GET `/angebote/aktueller_zeitraum/index.html`, bereinigt.
- `kurssuche.js` – GET `/angebote/aktueller_zeitraum/kurssuche.js`, bereinigt.
- `volleyball.html` – GET `/angebote/aktueller_zeitraum/_Volleyball.html`,
  bereinigt. Die Formular-Action wurde auf `/cgi/anmeldung.fcgi` relativiert;
  `BS_Code` ist `DUMMY`.
- `step1_live_redirect.html` – rohe Antwort des einen erlaubten POSTs
  (`BS_Code` + `BS_Kursid_31584`, keine persönlichen Daten). Sie ist eine
  Meta-Weiterleitung zur CMS-Anmeldung, weil der Volleyball-Kurs 32304
  passwortgeschützt ist (`value="buchen 🔒"`,
  `title="booking - password protected"`).

Der Submit-Name auf der Sportseite ist heute `BS_Kursid_31584` (nicht
`BS_Kursid_32304`). Die Kursnummer steht in der Zeile `id="K32304"`.

## Synthetisch (nicht live erreichbar)

- `step1_formular.html` – Personendaten-Formular, das nach dem ersten Schritt
  erwartet wird. Felder: `statusorig`, `vorname`, `name`, `email`, `tnbed`
  (AGB), Submit `BS_Weiter`, Action `/cgi/anmeldung.fcgi`.
- `step2_uebersicht.html` – Übersicht mit `fid` und Submit
  `BS_Verbindlich` („verbindlich buchen“).
- `step3_bestaetigt.html` – Erfolgsseite „Buchung bestätigt“.

Die synthetischen Seiten vermeiden bewusst die Zeichenfolgen `login`,
`anmelden` und `/cms/`, weil der aktuelle `submit_booking`-Code darauf mit
`AuthError` abbricht.

## Bereinigung

- Absolute Portal-URLs wurden entfernt bzw. auf relative Pfade umgestellt.
- `BS_Code` und UUID-artige Tokens wurden durch `DUMMY` ersetzt.
- Keine Cookies, Session-IDs oder persönlichen Daten in den Fixtures.
- Die Live-Seiten waren latin-1; die Fixtures liegen als UTF-8 vor und werden
  vom Fake-Server mit `charset=utf-8` ausgeliefert.
