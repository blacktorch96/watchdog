# Watchdog – Zentraler Statusdienst

Watchdog ist ein leichtgewichtiger HTTP-Statusdienst für externe Tools und Skripte.
Tools melden ihren Status per GET oder POST. Der Dienst speichert den Verlauf,
zeigt ein Live-Dashboard und sendet Alert-Mails bei Timeouts.

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

## Beispielaufrufe

### curl (bash / Linux / macOS)

```bash
# Status melden (GET)
curl "http://watchdog.example.com/watchdog?server=db01&dienst=backup&gruppe=Backup/DB&status=start&kommentar=Gestartet&pid=1234"

# Status melden (POST, JSON)
curl -X POST http://watchdog.example.com/watchdog \
  -H "Content-Type: application/json" \
  -d '{"server":"db01","dienst":"backup","status":"stop","kommentar":"OK","pid":"1234"}'

# In Shell-Skripten (Heartbeat-Pattern)
curl -sf "http://watchdog.example.com/watchdog?server=$(hostname)&dienst=myjob&status=start" || true
# ... Job-Logik ...
curl -sf "http://watchdog.example.com/watchdog?server=$(hostname)&dienst=myjob&status=stop" || true
```

### PowerShell (Windows)

```powershell
# Status melden (POST)
Invoke-RestMethod -Uri "http://watchdog.example.com/watchdog" `
  -Method Post `
  -Body @{
    server    = $env:COMPUTERNAME
    dienst    = "backup"
    status    = "start"
    kommentar = "Backup gestartet"
  }

# In PowerShell-Skripten (Heartbeat-Pattern)
Invoke-RestMethod "http://watchdog.example.com/watchdog?server=$env:COMPUTERNAME&dienst=myjob&status=start"
# ... Job-Logik ...
Invoke-RestMethod "http://watchdog.example.com/watchdog?server=$env:COMPUTERNAME&dienst=myjob&status=stop"
```

### Python (Stdlib, kein requests nötig)

```python
import urllib.request, urllib.parse, socket

BASE = "http://watchdog.example.com/watchdog"

def ping(status: str, kommentar: str = "", pid: str = ""):
    params = urllib.parse.urlencode({
        "server":    socket.gethostname(),
        "dienst":   "myjob",
        "status":   status,
        "kommentar": kommentar,
        "pid":       pid,
    })
    urllib.request.urlopen(f"{BASE}?{params}", timeout=5)

# Verwendung
ping("start", "Job gestartet")
# ... Job-Logik ...
ping("stop", "Fertig")
```

---

## Dashboard

Aufrufbar unter `/` – industrielles Dark-UI mit Sidebar und Detailpanel:

| Element | Beschreibung |
|---|---|
| **Sidebar** | Liste aller Services mit Status-Dot (pulsierend bei OK), Alter des letzten Pings, Intervall und **LATE**-Badge bei Timeout |
| **Overview-Tab** | Ping-History-Strip (60 Slots farbcodiert), Endpoint-URL mit kopierbaren Code-Snippets (curl, PowerShell, Python) |
| **History-Tab** | Chronologische Ereignisliste der letzten 20 Meldungen |
| **Statusleiste** | Uhrzeit + Versionsnummer unten links in der Sidebar |

**Status-Farbcodierung:**

| Farbe | Bedeutung |
|---|---|
| Grün | `start` – Tool läuft |
| Grau | `stop` – Tool beendet |
| Amber | `update` – Info-Meldung |
| Rot | `fehler` oder Timeout überschritten |

Das Dashboard aktualisiert sich automatisch alle 30 Sekunden.

---

## Admin-Oberfläche

| URL | Funktion |
|---|---|
| `/admin/tools` | Liste aller Tools, neu anlegen, löschen |
| `/admin/tools/new` | Tool manuell anlegen |
| `/admin/tools/<id>` | Gruppe, Timeout-Stunden, monatlichen Lauftag bearbeiten |
| `/admin/tools/<id>/history` | Meldungshistorie einsehen, Einträge manuell als „OK" markieren |
| `/admin/config` | SMTP-Host/Port, Alert-Empfänger, Check-Intervall, Toleranztage |

---

## Timeout-Logik

### Standard-Timeout

Ein Tool gilt als ausgefallen, wenn `now − last_seen > timeout_hours` (Default: 24 h).

### Monatlicher Timeout

Wenn `monthly_day` gesetzt ist, erwartet Watchdog eine Meldung jeden Monat an diesem Tag.
Fehlt sie länger als `monthly_grace_days` (Default: 5 Tage) nach dem erwarteten Tag, wird ein Alert verschickt.

### Alert-Mail

- Wird **einmalig** verschickt, sobald ein Timeout erkannt wird.
- Wird **zurückgesetzt**, wenn das Tool sich erneut meldet.
- SMTP ohne Authentifizierung (konfigurierbar unter `/admin/config`).

---

## Datenbankpfad

Die SQLite-Datenbank liegt unter `instance/watchdog.db` und wird beim ersten Start automatisch angelegt.
Der `instance/`-Ordner ist in `.gitignore` ausgeschlossen.

---

## Versionierung

Die Version wird zur Laufzeit aus `pyproject.toml` gelesen und im Dashboard (Sidebar, unten links) angezeigt.
Nach jeder abgeschlossenen Phase oder Feature-Umsetzung das `version`-Feld in `pyproject.toml` erhöhen.
