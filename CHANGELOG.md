# Changelog

Alle wesentlichen Änderungen an Open Signage werden in dieser Datei
dokumentiert.

Das Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/).
Die Versionsnummern folgen [Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

## [0.8.0] – 2026-08-08

### Hinzugefügt

- Frei vergebbarer Bildschirmname auf der Systemseite und Anzeige dieses
  Namens in der Überschrift der Inhalte-Seite.
- Passwortgeschützte Systemseite mit zwölf Stunden gültiger Sitzung und einer
  Funktion zum Ändern des Passworts.
- Anwendungsupdate über Git-Release-Tags mit neuer virtueller Umgebung,
  Healthcheck und automatischem Rollback.
- Status- und Protokollanzeige für Anwendungsupdates auf der Systemseite.

### Geändert

- Standard-Anzeigedauer für neu angelegte Webseiten von 30 auf 12 Sekunden
  reduziert.
- Systeminformationen und Systemupdates sind nur noch nach Anmeldung
  erreichbar.
- Projektversion von `0.7.0` auf `0.8.0` erhöht.

## [0.7.0] – 2026-08-08

### Hinzugefügt

- Upload und Playlistunterstützung für PDF-Dokumente.
- Prüfung der tatsächlichen PDF-Dateisignatur beim Upload.
- Vollbilddarstellung von PDFs im Chromium-Player ohne sichtbare Werkzeugleisten.

### Geändert

- Projektversion von `0.6.0` auf `0.7.0` erhöht.

## [0.6.0] – 2026-08-08

### Hinzugefügt

- Eigene Verwaltungsseite „System“ mit Raspberry-Pi-Modell, Betriebssystem,
  Kernel, Laufzeit, Temperatur, Last, Arbeitsspeicher und Datenspeicher.
- Übersicht für WLAN- und Ethernet-Schnittstellen mit Verbindungsstatus,
  IP-Adressen, Gateway, MAC-Adresse und WLAN-SSID.
- Hintergrund-Systemupdate über eine fest definierte, privilegierte
  `systemd`-Path-/Service-Kombination.
- Anzeige von Updatezustand, Zeitpunkten und den letzten Protokollzeilen.
- Schutz vor mehrfach gleichzeitig gestarteten Systemupdates.

### Geändert

- Das Installations- und Prüfskript richtet die Systemupdate-Überwachung ein.
- Projektversion von `0.5.0` auf `0.6.0` erhöht.

## [0.5.0] – 2026-08-08

### Hinzugefügt

- Serverseitige Erkennung von Container-, Video- und Audio-Codecs bei
  Video-Uploads über `ffprobe`.
- Sichtbare Kompatibilitätswarnung mit konkreten Codecdetails und empfohlenen
  Zielformaten in der Verwaltungsoberfläche.
- Automatische Installation von FFmpeg/ffprobe auf dem Raspberry Pi.

### Geändert

- Uploads mit unbekanntem MIME-Typ werden zusätzlich anhand ihrer Dateiendung
  erkannt.
- Projektversion von `0.4.0` auf `0.5.0` erhöht.

## [0.4.0] – 2026-07-29

### Hinzugefügt

- Automatische Installation einer minimalen Wayland-/labwc-Umgebung auf
  Raspberry Pi OS Lite 64 Bit.
- Dedizierter, automatisch angelegter Kioskbenutzer `signage`.
- Automatische Konfiguration von Wayland, grafischem Systemstart und
  Desktop-Autologin.
- Native Chromium-Wiedergabe über das Wayland-Backend.
- Minimale Schriftpakete für eine korrekte Darstellung von Webseiten.

### Geändert

- Raspberry Pi OS Lite 64 Bit ist nun die vorgesehene Installationsbasis.
- Das Installationsskript benötigt keinen vorinstallierten Desktop und keinen
  bereits vorhandenen Desktop-Benutzer mehr.
- Projektversion von `0.3.0` auf `0.4.0` erhöht.

## [0.3.0] – 2026-07-29

### Hinzugefügt

- Installationsskript für Raspberry Pi OS 64 Bit.
- Gehärteter `systemd`-Dienst mit automatischem Neustart bei Fehlern.
- Automatischer Chromium-Kioskstart unter Raspberry Pi OS Desktop.
- Kiosk-Autoplay für Livestreams mit Ton.
- Konfigurierbarer Produktionsport.
- Prüfskript für Dienst, Verwaltungsoberfläche und Player.

### Geändert

- Projektversion von `0.2.0` auf `0.3.0` erhöht.

## [0.2.0] – 2026-07-29

### Hinzugefügt

- Eigener Inhaltstyp für Owncast-Livestreams.
- Direkte HLS-Wiedergabe mit lokal mitgeliefertem HLS.js.
- Automatischer Wiedergabestart und konfigurierbare Stummschaltung.
- Offline-, Puffer- und Fehleranzeige für Livestreams.
- Automatische Wiederverbindung nach Streamunterbrechungen.
- Zentrale Versionsdatei und sichtbare Versionsnummer in der Verwaltung.
- Versionsangabe im Status-Endpunkt `/api/health`.
- Automatische Migration vorhandener Playlists auf das erweiterte Datenmodell.

### Geändert

- Projektversion von `0.1.0` auf `0.2.0` erhöht.
- Entwicklungsstart für das `src`-Layout korrigiert.

## [0.1.0] – 2026-07-29

### Hinzugefügt

- Erste lauffähige Open-Signage-Version.
- Lokale FastAPI-Anwendung mit SQLite-Datenbank.
- Verwaltungsoberfläche für Bilder, Videos und Webseiten.
- Datei-Uploads und Playlistverwaltung.
- Reihenfolge, Aktivierung und Anzeigedauer je Inhalt.
- Vollbild-Player mit automatischem Inhaltswechsel.
- Lokale Entwicklungs- und Testumgebung.
