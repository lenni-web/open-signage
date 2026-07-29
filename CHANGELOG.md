# Changelog

Alle wesentlichen Änderungen an Open Signage werden in dieser Datei
dokumentiert.

Das Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/).
Die Versionsnummern folgen [Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

### Hinzugefügt

- Noch nicht veröffentlichte Änderungen werden zunächst hier gesammelt.

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

