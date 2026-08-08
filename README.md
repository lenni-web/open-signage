# Open Signage

Lokale Digital-Signage-Anwendung für einen Raspberry Pi. Der Pi stellt eine
Administrationsoberfläche im Netzwerk bereit und zeigt eine Playlist in einem
Chromium-Kioskfenster an.

## Aktueller MVP

- Bilder und Videos hochladen
- PDF-Dokumente hochladen und im Vollbild anzeigen
- Webseiten als Inhalte anlegen
- Owncast-Livestreams direkt per HLS wiedergeben
- Inhalte aktivieren, sortieren und mit einer Anzeigedauer versehen
- Vollbild-Player mit automatischem Wechsel
- Livestream-Autoplay, Offline-Anzeige und automatische Wiederverbindung
- lokale SQLite-Datenbank
- Live-Aktualisierung des Players ohne Seitenreload

Weitere SRT-Quellen können später über MediaMTX ergänzt werden.

### Systemverwaltung

Die Seite **System** zeigt Geräte-, Speicher- und Netzwerkinformationen des
Raspberry Pi. Dort kann außerdem ein Betriebssystemupdate gestartet werden.
Im Hintergrund führt ein separater root-Dienst fest definiert Folgendes aus:

```bash
apt-get update && DEBIAN_FRONTEND=noninteractive apt-get upgrade -y
```

Die Webanwendung selbst besitzt keine allgemeinen `sudo`-Rechte und kann keine
beliebigen Befehle übergeben. Der Fortschritt und die letzten Protokollzeilen
werden auf der Systemseite angezeigt. Ein Neustart wird nach dem Update nicht
automatisch durchgeführt.

Da Systemupdates derzeit von jedem Gerät mit Zugriff auf die Verwaltung
ausgelöst werden können, sollte Open Signage nur in einem vertrauenswürdigen
lokalen Netzwerk betrieben werden. Ein Login-Schutz ist als nächster
Sicherheitsschritt vorgesehen.

### Unterstützte Videoformate

Beim Upload prüft Open Signage den tatsächlichen Container sowie die Video-
und Audio-Codecs mit `ffprobe`. Zuverlässig unterstützt werden:

- MP4 mit H.264/AVC und optional AAC-Audio;
- WebM mit VP8 oder VP9 und optional Opus- oder Vorbis-Audio.

Abweichende Dateien werden weiterhin hochgeladen, aber in der Verwaltung mit
einer deutlichen Kompatibilitätswarnung gekennzeichnet. Für lokale Entwicklung
muss FFmpeg installiert sein; das Raspberry-Pi-Installationsskript übernimmt
dies automatisch.

### PDF-Dokumente

PDF-Dateien können wie Bilder oder Videos hochgeladen, sortiert und mit einer
Anzeigedauer versehen werden. Der Player öffnet das Dokument im integrierten
Chromium-PDF-Viewer ohne Werkzeugleisten und passt es an die Bildschirmbreite
an. Mehrseitige Dokumente werden als zusammenhängende Dokumentansicht
dargestellt; ein automatischer Wechsel der einzelnen PDF-Seiten ist noch nicht
enthalten.

## Lokal starten

Voraussetzung: Python 3.11 oder neuer.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
uvicorn --app-dir src open_signage.main:app --reload
```

Danach:

- Verwaltung: <http://127.0.0.1:8000/>
- Player: <http://127.0.0.1:8000/player>
- Status: <http://127.0.0.1:8000/api/health>

Die Datenbank und hochgeladene Medien werden standardmäßig im Ordner `data/`
angelegt. Mit `OPEN_SIGNAGE_DATA_DIR` kann ein anderer Speicherort gewählt
werden.

Die installierte Version wird oben rechts in der Verwaltungsoberfläche und
über `/api/health` angezeigt. Für Releases wird die Versionsnummer zentral in
`src/open_signage/version.py` nach dem Schema `MAJOR.MINOR.PATCH` gepflegt.
Die Versionshistorie steht im [CHANGELOG.md](CHANGELOG.md).

## Tests

```bash
pytest
```

## Raspberry-Pi-Installation

Vorgesehene Basis ist **Raspberry Pi OS Lite 64 Bit**. Bei der Einrichtung im
Raspberry Pi Imager sollten Netzwerk, ein administrativer Benutzer und SSH
konfiguriert werden. Ein Desktop muss nicht installiert werden.

Im geklonten Projekt:

```bash
sudo ./scripts/install-raspberry-pi.sh --port 8080
```

Das Skript:

- installiert nur den Raspberry-Pi-Wayland-Kern mit labwc, Chromium und die
  Python-Laufzeit;
- legt den nicht-administrativen Kioskbenutzer `signage` an;
- aktiviert den grafischen Start und meldet `signage` automatisch an;
- kopiert Open Signage nach `/opt/open-signage`;
- speichert Daten und Medien unter `/var/lib/open-signage`;
- richtet den Dienst `open-signage.service` ein;
- startet Chromium nativ unter Wayland im Kioskmodus;
- prüft Server, Verwaltung und Player.

Ein abweichender Kioskbenutzer ist möglich:

```bash
sudo ./scripts/install-raspberry-pi.sh --kiosk-user display --port 8080
```

Manuelle Prüfung:

```bash
sudo ./scripts/verify-installation.sh --port 8080
systemctl status open-signage.service
journalctl -u open-signage.service -f
```

Der Dienst startet nach einem Stromausfall automatisch. Chromium wartet vor
dem Öffnen des Players, bis der lokale Server erreichbar ist. Nach der ersten
Installation ist ein Neustart erforderlich:

```bash
sudo reboot
```

Noch geplant sind ein Update-Skript, `open-signage.local`, Login-Schutz und
MediaMTX für zusätzliche direkte SRT-Quellen.

## Owncast-Livestream

Unter **Owncast-Livestream hinzufügen** genügt die Basisadresse der Instanz,
beispielsweise `https://stream.mg-stade.de`. Open Signage verwendet daraus
automatisch den HLS-Endpunkt `/hls/stream.m3u8`.

Stummes Autoplay funktioniert in normalen Browsern am zuverlässigsten. Für
automatischen Ton wird Chromium auf dem Raspberry Pi später mit
`--autoplay-policy=no-user-gesture-required` im Kioskmodus gestartet.

HLS-Wiedergabe in Chromium erfolgt mit der lokal mitgelieferten Bibliothek
HLS.js 1.6.16. Deren Lizenz liegt unter
`src/open_signage/static/vendor/HLS-LICENSE`.
