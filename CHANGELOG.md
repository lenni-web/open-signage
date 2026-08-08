# Changelog

Alle wesentlichen Änderungen an Open Signage werden in dieser Datei
dokumentiert.

Das Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/).
Die Versionsnummern folgen [Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

## [0.9.3] – 2026-08-08

### Hinzugefügt

- Optionale Zeitplanung je Playlist-Inhalt mit Start- und Endzeitpunkt,
  auswählbaren Wochentagen sowie täglichen Zeitfenstern.
- Zeitfenster über Mitternacht und komfortable Zeitplanverwaltung in der
  Inhalte-Seite.

### Geändert

- Der Player berücksichtigt die lokale Raspberry-Pi-Zeit und zeigt nur
  aktuell freigegebene Inhalte an.
- Projektversion von `0.9.2` auf `0.9.3` erhöht.

## [0.9.2] – 2026-08-08

### Hinzugefügt

- Schattenboxen für Freitext-Inhalte können in den Intensitäten `Light`,
  `Medium` und `Dark` konfiguriert werden.

### Geändert

- Der Player lädt das zuerst benötigte Bild mit hoher Priorität und weitere
  Bilder sowie Freitext-Hintergründe vorausschauend im Hintergrund.
- Medien mit UUID-Dateinamen erhalten langfristige unveränderliche
  Browser-Cache-Header für schnellere erneute Anzeige.
- Projektversion von `0.9.1` auf `0.9.2` erhöht.

## [0.9.1] – 2026-08-08

### Behoben

- Anwendungsupdates zeigen während des erwarteten Serverneustarts nicht mehr
  fälschlich „Load failed“, stellen die Verbindung automatisch wieder her und
  laden die Oberfläche nach erfolgreichem Abschluss neu.
- Anmeldesitzungen werden in SQLite gespeichert und bleiben dadurch bei einem
  Anwendungsneustart während des Updates gültig.
- Der Anwendungs-Updater aktualisiert künftig auch seinen privilegierten
  Helfer und die zugehörigen systemd-Units.

### Geändert

- Die Bereiche „Sicherheit“, „Anwendungsupdate“ und „Systemupdate“ sind auf der
  Systemseite einklappbar und standardmäßig geschlossen.
- Projektversion von `0.9.0` auf `0.9.1` erhöht.

## [0.9.0] – 2026-08-08

### Hinzugefügt

- Neue Verwaltungsseite „Mediathek“ zum dauerhaften Speichern von Fotos und
  Videos und zum direkten Hinzufügen vorhandener Medien zur Playlist.
- Auswahl eines bereits gespeicherten Mediathek-Bildes als Hintergrund für
  neue und bestehende Freitext-Inhalte.
- Neuer Playlist-Inhalt „Freitext“ mit Hintergrundbild, Überschrift,
  Unterüberschrift, Fließtext und optionaler Schattenbox.
- Vorschau vor dem Speichern sowie nachträgliches Bearbeiten bestehender
  Freitext-Inhalte einschließlich optionalem Austausch des Hintergrundbilds.

### Geändert

- Seitenüberschriften verwenden nun dieselbe zentrierte Inhaltsbreite wie die
  darunterliegenden Karten.
- Die gesamte Verwaltungsoberfläche einschließlich Inhalte-Seite und aller
  schreibenden Inhalts-APIs ist nur noch nach Anmeldung erreichbar.
- Der Player bezieht seine aktive Playlist über einen separaten,
  schreibgeschützten Endpunkt und benötigt weiterhin keine Anmeldung.
- Projektversion von `0.8.0` auf `0.9.0` erhöht.

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
