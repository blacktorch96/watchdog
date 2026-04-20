# Watchdog – Zentraler Statusdienst

Watchdog ist ein leichtgewichtiger HTTP-Statusdienst für externe Tools und Skripte.
Tools melden ihren Status per GET oder POST. Der Dienst speichert den Verlauf, zeigt ein Live-Dashboard und sendet Alert-Mails bei Timeouts.

---

## Tech Stack

| Komponente | Wahl |
|---|---|
| Framework | Flask (Application Factory) |
| Datenbank | SQLite (in `instance/`) |
| Scheduler | APScheduler (Background-Jobs) |
| Frontend | Jinja2 + Vanilla JS (Polling alle 30 s) |
| Pakete | uv |
| Python | ≥ 3.13 |

---

## Setup

### Voraussetzungen

- Python ≥ 3.13
- [uv](https://docs.astral.sh/uv/) installiert

### Installation

```bash
git clone <repo-url>
cd watchdog
uv sync
```

### Starten (Entwicklung)

```bash
uv run python wsgi.py
```

Öffne <http://localhost:5000> für das Dashboard.

### Starten (Produktion hinter nginx)

```bash
uv run gunicorn wsgi:app -w 2 -b 127.0.0.1:8000
```

Nginx-Beispielkonfiguration:

```nginx
server {
    listen 80;
    server_name watchdog.example.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## API

### Status melden

```
GET  /watchdog
POST /watchdog
```

**Parameter** (GET als Query-String, POST als Form-Data oder JSON):

| Parameter | Pflicht | Beschreibung |
|---|---|---|
| `server` | ja | Servername (frei wählbar, z.B. Hostname) |
| `dienst` | ja | Dienstname (frei wählbar) |
| `status` | ja | `start` · `stop` · `fehler` · `update` |
| `gruppe` | nein | Gruppenpfad, `/`-separiert, z.B. `Backup/Datenbank` |
| `kommentar` | nein | Freitext-Nachricht |
| `pid` | nein | Prozess-ID zur Zuordnung zusammengehöriger Events |

**Antwort:**

```json
{ "ok": true }
```

Ein unbekanntes Tool wird beim ersten Aufruf automatisch angelegt.

---

## Beispiel-Curl-Befehle

```bash
# Backup gestartet
curl "http://watchdog.example.com/watchdog?server=db01&dienst=backup&gruppe=Backup/Datenbank&status=start&kommentar=Backup+gestartet&pid=1234"

# Backup erfolgreich beendet
curl "http://watchdog.example.com/watchdog?server=db01&dienst=backup&status=stop&kommentar=Backup+OK&pid=1234"

# Fehler melden
curl -X POST http://watchdog.example.com/watchdog \
  -H "Content-Type: application/json" \
  -d '{"server":"db01","dienst":"backup","status":"fehler","kommentar":"Verbindung abgebrochen"}'

# In Shell-Skripten (Heartbeat)
curl -sf "http://watchdog.example.com/watchdog?server=$(hostname)&dienst=myjob&status=start" || true
# ... Job-Logik ...
curl -sf "http://watchdog.example.com/watchdog?server=$(hostname)&dienst=myjob&status=stop" || true
```

---

## Dashboard

Aufrufbar unter `/` – zeigt alle Tools gruppiert nach `gruppe`, farblich nach Status:

| Farbe | Bedeutung |
|---|---|
| Grün | `start` – Tool läuft |
| Grau | `stop` – Tool beendet |
| Orange | `fehler` – Fehler gemeldet |
| Rot | Timeout – seit zu langer Zeit keine Meldung |

Das Dashboard aktualisiert sich automatisch alle 30 Sekunden via JavaScript-Polling.

---

## Admin-Oberfläche

| URL | Funktion |
|---|---|
| `/admin/tools` | Liste aller Tools, löschen, neu anlegen |
| `/admin/tools/<id>` | Tool-Konfiguration bearbeiten |
| `/admin/tools/<id>/history` | Meldungshistorie eines Tools |
| `/admin/config` | SMTP-Konfiguration, Alert-Empfänger |

---

## Timeout-Logik

### Standard-Timeout

Ein Tool gilt als ausgefallen, wenn `now − last_seen > timeout_hours` (Default: 24 h).

### Monatlicher Timeout

Wenn `monthly_day` gesetzt ist, erwartet Watchdog eine Meldung jeden Monat an diesem Tag.
Fehlt eine Meldung länger als `monthly_grace_days` (Default: 5) nach dem erwarteten Tag,
wird ein Alert verschickt.

### Alert-Mail

- Wird **einmalig** verschickt, sobald ein Timeout erkannt wird.
- Wird **zurückgesetzt**, wenn das Tool sich erneut meldet.
- SMTP ohne Authentifizierung (konfigurierbar unter `/admin/config`).

---

## Datenbankpfad

Die SQLite-Datenbank liegt unter `instance/watchdog.db` und wird beim ersten Start automatisch angelegt.

---

## Tests ausführen

```bash
PYTHONIOENCODING=utf-8 uv run python test_phase2.py
PYTHONIOENCODING=utf-8 uv run python test_phase3.py
PYTHONIOENCODING=utf-8 uv run python test_phase4.py
```
