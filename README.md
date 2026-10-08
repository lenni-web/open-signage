# Open Signage

Lokale Digital-Signage-Anwendung für einen Raspberry Pi. Der Pi stellt eine
Administrationsoberfläche im Netzwerk bereit und zeigt eine Playlist in einem
Chromium-Kioskfenster an.

## Aktueller MVP

- Bilder und Videos hochladen; Videos wahlweise mit Ton und bis zum Dateiende
  wiedergeben
- PDF-Dokumente hochladen und im Vollbild anzeigen
- Webseiten als Inhalte anlegen
- Freitext mit Hintergrundbild, Überschrift, Unterüberschrift, Text und
  optionaler Schattenbox gestalten, vorab ansehen und später bearbeiten;
  inklusive Position, Farben, Schriften, Bildfokus, Abdunklung, Logo und
  wiederverwendbaren Designvorlagen
- Mediathek für dauerhaft gespeicherte Fotos und Videos, die mehrfach in die
  Playlist oder als Freitext-Hintergrund übernommen werden können; direkte
  Bild- und Video-Uploads landen automatisch in der Mediathek
- Responsive Verwaltungsoberfläche für Desktop, Tablet und Smartphone
- Ausfallsicherer Player mit lokalem Playlist-Cache und Wiederaufnahme
- Speicherbereinigung, zeitgesteuerte Playlists und sichere Systemaktionen
- Geräteidentität und Betriebsmodi für Standalone, Controller und Display
- HDMI-CEC-Bildschirmsteuerung mit frei kombinierbaren Zeitfenstern, mehreren
  Ein-/Ausschaltphasen je Wochentag und Eingangswahl. Antwortet ein Display
  nicht auf CEC, wird automatisch Wayland-DPMS über `wlopm` verwendet.
- Kompakte Inhaltsverwaltung mit auswählbaren Formularen sowie Freitext auf
  Bild- oder stummem Video-Hintergrund
- Bildeditor mit 16:9-Zuschnitt, Drehung, Fokus, Helligkeit und Kontrast sowie
  automatisch erzeugten Full-HD- und Thumbnail-Dateien
- Mediathek-Suche, Kategorien, Nutzungsfilter, Mehrfachauswahl, Video-
  Thumbnails, direkte Vorschau und optimale Konvertierung nach MP4/H.264/AAC
- Owncast-Livestreams direkt per HLS wiedergeben
- Live-Übertragungen aus OBS mit geringer Verzögerung per WebRTC (WHIP/WHEP)
  wiedergeben, als Playlist-Inhalt oder per „Live jetzt übernehmen“
- Inhalte aktivieren, sortieren und mit einer Anzeigedauer versehen
- Inhalte nach Datum, Uhrzeit und Wochentagen zeitgesteuert anzeigen
- Mehrere getrennte Playlists anlegen und die aktive Wiedergabe umschalten
- Vollbild-Player mit automatischem Wechsel
- Livestream-Autoplay, Offline-Anzeige und automatische Wiederverbindung
- lokale SQLite-Datenbank
- Live-Aktualisierung des Players ohne Seitenreload
- Player-Monitoring mit aktuellem Inhalt, letztem Kontakt, Fehlerprotokoll,
  Speicher-, Temperatur- und Updatezustand
- tägliche geprüfte SQLite-Backups, manuelle Komplettsicherungen und Restore
- Sicherheitsstatus und Mediathek-Audit für fehlende, verwaiste und doppelte Medien
- Controller-/Display-Synchronisierung mit Geräte-Pairing und lokalem Offline-Stand

### Systemverwaltung

Die passwortgeschützte Seite **System** zeigt Geräte-, Speicher- und
Netzwerkinformationen des Raspberry Pi. Bei der Installation wird ein zufälliges
Initialpasswort ausgegeben. Bis zu dessen Änderung sind schreibende Aktionen
gesperrt. Außerdem kann ein
Bildschirmname vergeben und ein Betriebssystemupdate gestartet werden.

Die Anmeldung schützt die gesamte Verwaltungsoberfläche einschließlich der
Inhalte-Seite. Nach fünf Fehlversuchen innerhalb von 15 Minuten wird die
Client-Adresse für 15 Minuten gesperrt. Eine Anmeldung bleibt auch während eines
Anwendungsneustarts gültig und läuft nach zwölf Stunden ab.

Der Player authentifiziert sich mit einem automatisch erzeugten Geräteschlüssel.
Der Kiosk auf dem Gerät selbst erhält ihn immer, Geräte aus privaten IPv4-/IPv6-
Netzen standardmäßig ebenfalls ohne Anmeldung. Unter **Einstellungen →
Sicherheit → Player-Zugriff** lässt sich diese LAN-Freigabe abschalten; andere
Geräte müssen den Player dann einmalig mit dem Verwaltungspasswort
freischalten. Mediendateien unter `/media` werden nach derselben Regel
ausgeliefert: an berechtigte Player und angemeldete Verwaltungssitzungen, aber
nicht an unbekannte Clients außerhalb lokaler Netze.

Uploads werden anhand ihres tatsächlichen Dateiinhalts geprüft und standardmäßig
auf 1 GiB begrenzt. Mindestens 512 MiB beziehungsweise fünf Prozent des
Datenträgers bleiben reserviert. Videos müssen durch `ffprobe` vollständig lesbar
sein. Optimale Videokonvertierungen laufen nacheinander im Hintergrund, verwenden
höchstens zwei ffmpeg-Threads und werden nach 30 Minuten beendet.

SQLite verwendet WAL, ein zehnsekündiges `busy_timeout` und führt beim Start sowie
anschließend täglich einen Integritätscheck aus.
Im Hintergrund führt ein separater root-Dienst fest definiert Folgendes aus:

```bash
apt-get update && DEBIAN_FRONTEND=noninteractive apt-get upgrade -y
```

Die Webanwendung selbst besitzt keine allgemeinen `sudo`-Rechte und kann keine
beliebigen Befehle übergeben. Der Fortschritt und die letzten Protokollzeilen
werden auf der Systemseite angezeigt. Ein Neustart wird nach dem Update nicht
automatisch durchgeführt.

Die Systeminformationen, Einstellungen und das Auslösen von Systemupdates sind
nur mit einer gültigen Anmeldung erreichbar.

### Backup und Wiederherstellung

Open Signage erstellt beim Start und anschließend täglich eine konsistente
SQLite-Onlinekopie. Automatische Sicherungen bewahren sieben tägliche Stände und
bis zu vier zusätzliche Wochenstände auf. Auf der Systemseite können manuelle
Backups wahlweise mit allen Medien erzeugt, heruntergeladen und wiederhergestellt
werden. Vor jeder Wiederherstellung wird automatisch eine vollständige
Sicherheitssicherung des aktuellen Zustands angelegt. Nach einem Restore sollte
der Open-Signage-Dienst neu gestartet werden.

### Controller und Displays

Auf dem Controller wird unter **System → Controller-/Display-Synchronisierung**
der Modus `Controller` gewählt. Der danach angezeigte Pairing-Code wird einmalig
auf dem Display zusammen mit der Controller-Adresse eingetragen. Bei der ersten
Synchronisierung registriert der Controller das Gerät und vergibt einen eigenen
zufälligen Token.

Synchronisiert werden Bildschirmname, Bildschirmsteuerung, Playlists, Inhalte
und Mediathek-Dateien. Das Display prüft minütlich auf Änderungen; über „Jetzt
synchronisieren“ lässt sich der Vorgang sofort auslösen. Ist der Controller nicht
erreichbar, spielt das Display seinen zuletzt vollständig synchronisierten lokalen
Stand weiter. Verwaltungspasswörter, Geräterollen und Geräte-Tokens bleiben
absichtlich gerätespezifisch.

Der Raspberry-Pi-Installer akzeptiert den Betriebsmodus direkt:

```bash
sudo ./scripts/install-raspberry-pi.sh --mode controller
sudo ./scripts/install-raspberry-pi.sh --mode display \
  --controller-url http://open-signage-controller.local:8080
```

Im Display-Modus zeigt die Verwaltung nur lokale Diagnose, Verbindung,
Sofortsynchronisierung, Updates, Bildschirmaktionen und den kontrollierten
Moduswechsel. Inhalts-, Playlist-, Mediathek- und zentrale Einstellungsänderungen
werden zusätzlich serverseitig blockiert. Bestehende Rollen werden automatisch
von `master` auf `controller` und von `slave` auf `display` migriert.

Controller und Displays dürfen kurzzeitig unterschiedliche Versionen haben.
Einträge, die ein älteres Display noch nicht kennt – etwa ein neuer
Inhaltstyp –, überspringt es beim Abgleich und weist im
Synchronisationsstatus darauf hin; alle übrigen Inhalte werden weiter
übernommen. Displays sollten trotzdem zeitnah aktualisiert werden.

### Open Signage aktualisieren

Die Systemseite kann den neuesten veröffentlichten Open-Signage-Release
installieren. Das Installationsskript merkt sich dazu das ursprünglich geklonte
Git-Repository und dessen Benutzer. Der Updater lädt neue Git-Tags über den
dort eingerichteten SSH-Zugang, installiert den höchsten Versions-Tag zunächst
getrennt und prüft nach dem Neustart `/api/health`. Bei einem fehlgeschlagenen
Healthcheck stellt er automatisch die vorherige Version wieder her.

Pakete, Systemdienste und Kiosk-Einstellungen richtet das Skript
`deploy/open-signage-post-update` der *neuen* Version ein, bevor umgeschaltet
wird. Dadurch kann jede Version eigene Systemdienste mitbringen. Schlägt ein
Schritt vor der Umschaltung fehl, bricht der Updater ab und die laufende
Version bleibt unverändert.

Nur getaggte Releases werden installiert. Änderungen auf `main`, die noch
keinen Versionstag besitzen, werden nicht automatisch ausgerollt.

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
dargestellt; die einzelnen Seiten werden nicht automatisch weitergeblättert.

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

- installiert nur den Raspberry-Pi-Wayland-Kern mit labwc, Chromium, `wlopm`
  und die Python-Laufzeit;
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

Kiosk- und Chromiumfehler werden unter
`/home/signage/.local/state/open-signage/kiosk.log` protokolliert, bei einem
abweichenden `--kiosk-user` entsprechend in dessen Home-Verzeichnis. Chromium
verwendet ein eigenes beschreibbares Profil und wird nach einem unerwarteten
Ende automatisch neu gestartet. Die Browsersprache und bevorzugte
Webseitensprache sind auf Deutsch eingestellt; die automatische
Übersetzungsleiste ist für den Kioskbetrieb deaktiviert. Der Vollbild-Player
blendet den Mauszeiger dauerhaft aus. Ein nativer Labwc-Cursorwächter erfasst
dabei auch eingebettete Webseiten und PDFs, deren Cursor sich nicht per
Player-CSS steuern lässt.

Die Bildschirmsteuerung prüft alle vorhandenen CEC-Adapter. Ein Display gilt
erst dann als CEC-fähig, wenn es selbst antwortet. Andernfalls schaltet Open
Signage den aktuell verbundenen Wayland-Ausgang per DPMS aus und wieder ein.
Damit funktionieren sowohl CEC-fähige Fernseher als auch Monitore, die bei
fehlendem HDMI-Signal automatisch in den Standby wechseln.

```bash
sudo reboot
```

## Live-Übertragung aus OBS

Für Live-Bilder mit möglichst geringer Verzögerung sendet OBS Studio (ab
Version 30) per WebRTC an den mitgelieferten Live-Server
[MediaMTX](https://github.com/bluenviron/mediamtx). Der Player spielt das Bild
ohne erneutes Codieren ab; die Verzögerung liegt typischerweise unter einer
Sekunde.

Die Zugangsdaten stehen unter **Inhalte → Live-Übertragung → OBS einrichten**.
In OBS unter *Einstellungen → Stream*:

- Dienst: `WHIP`
- Server: `http://<adresse-des-pi>:8889/live/whip`
- Bearer-Token: der angezeigte Wert `obs:…`

Empfohlen unter *Ausgabe*: 1080p30, Keyframe-Intervall 1 s und keine B-Frames
(bei x264 das Profil „baseline“).

Die Wiedergabe lässt sich auf zwei Arten nutzen:

- **Live jetzt übernehmen** unterbricht die Playlist sofort auf allen Playern.
  Nach **Live beenden** – oder optional automatisch 20 Sekunden nachdem OBS den
  Stream beendet hat – läuft die Playlist weiter.
- Der Inhaltstyp **Live-Übertragung aus OBS** spielt das Live-Bild als
  regulären Playlist-Eintrag. Sendet OBS nicht, wird er übersprungen.

Im Controller-Betrieb sendet OBS nur an den Controller. Displays beziehen das
Bild bei Bedarf über RTSP vom Controller, die Übernahme wird innerhalb weniger
Sekunden auf alle Displays übertragen. Im Netzwerk müssen dafür die Ports
8889/TCP (WHIP), 8189/UDP (WebRTC) und 8554 (RTSP zwischen Controller und
Displays) erreichbar sein.

Der Installer und der Anwendungsupdater richten MediaMTX in einer festen,
per SHA-256 geprüften Version als Dienst `open-signage-mediamtx.service` ein.
Bei einem Update von einer älteren Version fordert Open Signage die
Einrichtung nach dem Neustart selbst an; alternativ steht in der Verwaltung
**Live-Server einrichten** zur Verfügung. Die Konfiguration erzeugt Open
Signage unter `/var/lib/open-signage/mediamtx.yml`. Abspielen dürfen nur der
lokale Server und berechtigte Player; Senden erfordert das OBS-Token.

## Owncast-Livestream

Unter **Owncast-Livestream hinzufügen** genügt die Basisadresse der Instanz,
beispielsweise `https://stream.mg-stade.de`. Open Signage verwendet daraus
automatisch den HLS-Endpunkt `/hls/stream.m3u8`.

Stummes Autoplay funktioniert in normalen Browsern am zuverlässigsten. Der
Kiosk auf dem Raspberry Pi startet Chromium mit
`--autoplay-policy=no-user-gesture-required`, sodass dort auch Ton automatisch
abgespielt wird.

HLS-Wiedergabe in Chromium erfolgt mit der lokal mitgelieferten Bibliothek
HLS.js 1.6.16. Deren Lizenz liegt unter
`src/open_signage/static/vendor/HLS-LICENSE`.
