# Changelog

Alle wesentlichen Änderungen an Open Signage werden in dieser Datei
dokumentiert.

Das Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/).
Die Versionsnummern folgen [Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

### Geändert

- Die weiche Player-Deckblende wurde von fünf auf vier Sekunden verkürzt. Ihre
  ruhige Kurve und die flackerarmen Compositor-Ebenen bleiben unverändert.
- Unter Einstellungen lässt sich die Überblendzeit mit einem kompakten Regler
  zwischen 1.000 und 6.000 Millisekunden festlegen. Der authentifizierte Player
  übernimmt Änderungen automatisch; Standardwert sind 4.000 Millisekunden.
- Controller und Displays berechnen Prüfsummen unveränderter Mediendateien
  nicht mehr bei jeder Synchronisierung neu. Das entlastet Prozessor und
  Speicherkarte besonders bei großen Videos.
- Displays entfernen nach einer erfolgreichen Synchronisierung Mediendateien,
  die der Controller-Stand nicht mehr verwendet.

### Behoben

- Netzwerkbrowser bleiben auf der Player-Seite nicht mehr irreführend bei
  „Warte auf Inhalte“ stehen. Geräte aus privaten IPv4-/IPv6-Netzen werden
  automatisch als reine Player autorisiert, erhalten aber keine Verwaltungs-
  sitzung. Nur Zugriffe außerhalb lokaler Netze benötigen eine einmalige
  geschützte Player-Freischaltung.
- PDFs, Freitext-Logos und direkt hochgeladene Freitext-Hintergründe werden
  jetzt auf Displays synchronisiert. Die Speicherprüfung meldet sie nicht mehr
  als verwaist, und „Verwaiste Dateien bereinigen“ löscht sie nicht mehr.
- Die Display-Synchronisierung bleibt auch dann funktionsfähig, wenn der
  Controller eine neuere Version mit zusätzlichen Datenbankspalten verwendet.
  Datenbankfehler beenden die minütliche Synchronisierung nicht mehr dauerhaft.

## [0.14.0] – 2026-08-11

### Geändert

- Deckblenden dauern nun fünf Sekunden und verwenden eine besonders flache,
  gleichmäßige Ein-/Auslaufkurve ohne ausgeprägte Beschleunigung in der Mitte.
  Player-Ebenen bleiben dauerhaft als isolierte
  Compositor-Flächen vorbereitet, damit insbesondere bei einfachen Bildern
  keine kurzfristige GPU-Umschaltung als dunkler Einzelbildblitz erscheint.
- Die Systemseite bietet eine dauerhafte Auflösungswahl für automatisch,
  1080p/60, 1080p/50 und 720p/60. Der HDMI-Ausgang wird automatisch erkannt,
  der Modus beim Start, nach Hotplug und nach dem Einschalten angewendet. Nicht
  unterstützte Vorgaben fallen sicher auf den bevorzugten Bildschirmmodus
  zurück; neue Installationen verwenden standardmäßig 1080p/60.

## [0.13.5] – 2026-08-10

### Behoben

- Der Mauszeiger-Wächter erzeugt keine virtuellen Tastatureingaben mehr,
  solange alle Wayland-Ausgänge ausgeschaltet sind. Dadurch wird ein per
  Wayland-DPMS abgeschalteter Monitor nicht unbeabsichtigt wieder aufgeweckt.
  Der aktive Bildschirm-Zeitplan setzt seinen Ausschaltzustand zusätzlich
  regelmäßig erneut durch, falls HDMI-Hotplug den Ausgang reaktiviert.

## [0.13.4] – 2026-08-10

### Geändert

- Übergänge laufen nun über eine eigene, minimal sichtbare Compositor-Ebene und
  dauern zwei Sekunden. Videos werden erst nach zwei gerenderten Frames plus
  GPU-Beruhigungszeit eingeblendet; Webseiten erhalten vier Sekunden und PDFs
  1,2 Sekunden zum Warmrendern. Dadurch werden verzögert erscheinende
  Videohintergründe und harte `iframe`-Freischaltungen vermieden.
- Die Deckblende arbeitet nun umgekehrt: Der neue Inhalt wird vollständig
  deckend hinter dem aktuellen Inhalt warmgerendert, danach wird ausschließlich
  der alte Inhalt ausgeblendet. Bilder verwenden zudem keinen schwarzen
  Elementhintergrund mehr. Damit bleibt stets eine vollständig gerenderte Ebene
  sichtbar und der Wechsel wirkt als ruhige Überblendung statt als Lichtblitz.
- Die Deckblende dauert nun drei Sekunden und verwendet eine symmetrische,
  besonders sanft ein- und auslaufende Animationskurve.
- CEC-Schaltbefehle gelten erst dann als erfolgreich, wenn eine anschließende
  Statusabfrage den erwarteten Energiezustand bestätigt. Reagiert ein Monitor
  trotz erfolgreichem Prozessaufruf nicht auf CEC, übernimmt automatisch der
  aktivierte Wayland-DPMS-Fallback und die Oberfläche zeigt keinen falschen
  CEC-Erfolg mehr an.

## [0.13.3] – 2026-08-10

### Behoben

- Ein nativer Labwc-Cursorwächter blendet den Mauszeiger nun auch über
  eingebetteten, fremden Webseiten und PDFs aus. Nach Eingaben oder einem
  HDMI-Wake wird er automatisch erneut verborgen.
- Bei Player-Übergängen bleibt der bisherige Inhalt vollständig deckend, bis
  der vorgeladene neue Inhalt darüber eingeblendet ist. Dadurch scheint der
  schwarze Bühnenhintergrund während Bildwechseln nicht mehr durch.
- Webseiten und PDFs erhalten nach ihrem Ladeereignis zusätzlich Zeit für den
  ersten vollständig gerenderten Browserframe, bevor ihre Einblendung beginnt.
- WLAN und Ethernet bleiben auf üblichen Browserbreiten zuverlässig
  nebeneinander; erst unter 620 Pixeln wechselt der Netzwerkbereich auf eine
  Spalte. Versionsgebundene CSS-/JavaScript-URLs verhindern nach Updates einen
  Mischstand aus neuem HTML und alten Browser-Cache-Dateien.
- Inhaltswechsel kombinieren nun eine 1,4 Sekunden lange Deckblende mit einer
  dezenten Einschubbewegung. Freitext mit Video-Hintergrund wartet auf den
  ersten tatsächlich gerenderten Videoframe; Webseiten erhalten 2,5 Sekunden
  zusätzliche Aufbauzeit und PDFs 800 Millisekunden Renderzeit.
## [0.13.2] – 2026-08-10

### Geändert

- Der Chromium-Kiosk verwendet explizit Deutsch (`de-DE`) als Oberflächen-,
  Inhalts- und bevorzugte Webseitensprache; Installer und Updater richten die
  benötigte UTF-8-Locale automatisch ein.
- WLAN- und Ethernet-Informationen stehen auf breiten Systemseiten direkt
  nebeneinander und wechseln auf kleinen Bildschirmen in eine einspaltige
  Darstellung.
- Der Player lädt den nächsten Inhalt auf einer zweiten Ebene vor und blendet
  ihn weich über den bisherigen Inhalt. Bilder, Videos, Webseiten, PDFs,
  Freitext und Streams wechseln dadurch ohne schwarzen Zwischenframe.

### Behoben

- Die integrierte Google-Übersetzungsleiste wird über Startparameter und eine
  verwaltete Chromium-Richtlinie dauerhaft deaktiviert.
- Der Mauszeiger bleibt im Vollbild-Player dauerhaft ausgeblendet, auch nach
  Mausbewegungen oder dem erneuten Einschalten des HDMI-Ausgangs.

## [0.13.1] – 2026-08-10

### Geändert

- Die Verwaltungsoberfläche trennt Konfigurationen künftig unter
  `Einstellungen` von Diagnose und Wartung unter `System`. Anzeige,
  Betriebszustand, Raspberry-Pi-Systeminformationen, Netzwerk,
  Datenspeicher, Prüfungen sowie Anwendungs- und Betriebssystemupdate bleiben
  übersichtlich auf der Systemseite gebündelt.
- Die Bildschirmsteuerung prüft automatisch alle vorhandenen CEC-Adapter und
  verwendet bei Displays ohne CEC-Antwort den verbundenen Wayland-Ausgang über
  `wlopm`. Oberfläche und Status nennen den tatsächlich verwendeten
  Steuerungsweg und Ausgang.

### Behoben

- Der Labwc-Autostart wird ausführbar installiert; dadurch startet Chromium nach
  dem grafischen Autologin zuverlässig statt nur einen grauen Desktop zu zeigen.
- Der Kiosk setzt ein beschreibbares Home-, XDG- und Chromium-Profilverzeichnis,
  wodurch Crashpad-/Zygote-Abbrüche wegen fehlender Verzeichnisse vermieden werden.
- Chromium wird nach einem Absturz automatisch neu gestartet und schreibt ein
  dauerhaftes Diagnoseprotokoll nach
  `~/.local/state/open-signage/kiosk.log`.
- Installer und Anwendungs-Updater halten Kiosk-Skript und Labwc-Autostart bei
  künftigen Installationen und Updates gemeinsam aktuell.
- `cec-client`-Übertragungsfehler wie `CEC_TRANSMIT failed`, `tx_status=00` und
  `errno=64` gelten nicht mehr fälschlich als erfolgreiche Bildschirmaktion.
  Bei aktiviertem Fallback wird stattdessen Wayland-DPMS versucht und die
  verwendete Methode verständlich protokolliert.
- Der unter KMS wirkungslose `vcgencmd display_power`-Fallback wurde durch das
  unter Labwc bestätigte, symmetrische Ein- und Ausschalten mit `wlopm` ersetzt.

## [0.13.0] – 2026-08-10

### Geändert

- Die bisherigen Rollen `master` und `slave` heißen künftig `controller` und
  `display`; vorhandene Gerätekonfigurationen werden automatisch migriert.
- Der Raspberry-Pi-Installer unterstützt `--mode standalone|controller|display`
  und im Display-Modus eine verpflichtende `--controller-url`.
- Die Verwaltungsoberfläche reduziert sich im Display-Modus auf lokale Diagnose,
  Controller-Verbindung, Synchronisierung, Updates, Bildschirmaktionen und einen
  passwortgeschützten Moduswechsel.

### Sicherheit

- Im Display-Modus blockiert das Backend lokale Änderungen an Inhalten,
  Playlists, Mediathek, Backups und zentralen Einstellungen unabhängig von der
  ausgeblendeten Oberfläche. Nur ausdrücklich erlaubte lokale Wartungsaktionen
  bleiben schreibbar.
- Jeder nachträgliche Wechsel des Betriebsmodus verlangt erneut das lokale
  Administratorpasswort.

### Geändert

- Projektversion von `0.12.0` auf `0.13.0` erhöht.

## [0.12.0] – 2026-08-09

### Hinzugefügt

- Automatische tägliche, SQLite-konsistente Backups mit sieben täglichen und
  vier zusätzlichen wöchentlichen Aufbewahrungspunkten sowie Integritätsprüfung.
- Manuelle Backups mit optionalen Medien, Download, validiertem Upload und
  Wiederherstellung einschließlich automatisch angelegter Sicherheitssicherung.
- Sicherheitsstatus für Initialpasswort, Player-Token, Datenbankintegrität,
  Backups, Speicherreserve und HTTPS.
- Komfortfunktionen für den Bildschirm-Schaltplan: Tagesplan kopieren,
  Zeitfenster duplizieren, Gruppierung, Überschneidungswarnungen und Anzeige des
  nächsten Schaltvorgangs.
- Speicher-Audit für fehlende Medien, verwaiste Dateien, Speicherverbrauch und
  inhaltsgleiche Dubletten sowie Reparatur fehlender Mediathek-Dateien.
- Sichtbarer Uploadfortschritt für direkte Medien- und Mediathek-Uploads.
- Master-/Slave-Synchronisierung für Bildschirmname, Bildschirmsteuerung,
  Playlists, Inhalte und Medien mit Pairing-Code, individuellem Geräte-Token,
  manueller und minütlicher Synchronisierung sowie Offline-Weiterbetrieb.

### Sicherheit

- Master-Snapshots und Mediendateien sind ausschließlich für registrierte
  Geräte mit eigenem zufälligem Token erreichbar.

### Geändert

- Projektversion von `0.11.4` auf `0.12.0` erhöht.

## [0.11.4] – 2026-08-09

### Hinzugefügt

- Der Bildschirm-Schaltplan ist eine frei erweiterbare Liste mit bis zu 100
  Zeitfenstern. Dadurch sind mehrere Ein- und Ausschaltphasen am selben
  Wochentag sowie weiterhin Zeitfenster über Mitternacht möglich.

### Behoben

- Ältere oder unvollständige Bildschirmkonfigurationen mit fehlenden oder
  leeren `schedule_entries` werden im Backend und in der Verwaltungsoberfläche
  sicher als leerer Wochenplan behandelt.
- Die Sitzungsprüfung liefert im abgemeldeten Zustand eine reguläre Antwort,
  wodurch kein erwartbarer `401`-Fehler mehr in der Browserkonsole erscheint.
- Ein eingebettetes Favicon verhindert unnötige `favicon.ico`-Anfragen.
- Fehlende Dateien aus älteren Mediathek- oder Playlist-Einträgen werden als
  solche gekennzeichnet und vom Player übersprungen, statt wiederholt eine
  nicht vorhandene Medien-URL abzurufen.

### Geändert

- Projektversion von `0.11.3` auf `0.11.4` erhöht.

## [0.11.3] – 2026-08-09

### Hinzugefügt

- Persistenter Login-Schutz mit maximal fünf Fehlversuchen pro Client innerhalb
  von 15 Minuten und anschließender 15-minütiger Sperre.
- Zufälliges, bei der Raspberry-Pi-Installation ausgegebenes Initialpasswort;
  schreibende Verwaltungsaktionen bleiben bis zur Passwortänderung gesperrt.
- Eigener zufälliger Geräteschlüssel für Player-Inhaltsabruf und Heartbeat, dessen
  lokale Bereitstellung auf die Loopback-Schnittstelle begrenzt ist.
- Täglicher SQLite-Integritätscheck mit gespeichertem Prüfzeitpunkt und Ergebnis.
- Inhaltsbasierte Upload-Erkennung, laufende Speicherplatzprüfung und vollständige
  Videoanalyse über `ffprobe`.
- Persistenter Status für Videokonvertierungen, die nacheinander im Hintergrund
  ausgeführt und in der Oberfläche bis zum Ergebnis verfolgt werden.

### Geändert

- Der automatische Bildschirm-Zeitplan unterstützt individuelle Ein- und
  Ausschaltzeiten für jeden einzelnen Wochentag statt eines gemeinsamen
  Zeitfensters für alle ausgewählten Tage.
- Bestehende gemeinsame Bildschirmzeitpläne werden automatisch in das neue
  Wochenformat übernommen.
- SQLite verwendet WAL, `synchronous=NORMAL` und ein `busy_timeout` von zehn
  Sekunden.
- Das Standardlimit pro Upload beträgt 1 GiB; mindestens 512 MiB beziehungsweise
  fünf Prozent des Datenträgers bleiben frei.
- ffmpeg-Konvertierungen verwenden höchstens zwei Threads und werden nach
  30 Minuten abgebrochen.
- Projektversion von `0.11.2` auf `0.11.3` erhöht.

### Behoben

- Die regelmäßige Statusaktualisierung überschreibt keine noch nicht
  gespeicherten Eingaben mehr. Dadurch bleibt insbesondere der Haken bei
  „Automatischen Bildschirm-Zeitplan aktivieren“ während der Bearbeitung gesetzt.

## [0.11.2] – 2026-08-09

### Hinzugefügt

- Dezente, sekündlich aktualisierte lokale Uhrzeit oben links in der
  Verwaltungsoberfläche; das vollständige Datum steht als Tooltip bereit.
- HDMI-CEC-Bildschirmsteuerung mit Ein-/Ausschaltbuttons, konfigurierbarer
  logischer CEC-Adresse und optionaler Aktivierung des angeschlossenen
  HDMI-Eingangs.
- Automatischer Ein-/Ausschaltzeitplan nach Wochentagen und Uhrzeiten,
  einschließlich Zeitfenstern über Mitternacht.
- Anzeige von CEC-Verfügbarkeit, erkanntem Bildschirmstatus, verwendeter
  Steuerungsmethode und letzter Statusmeldung auf der Systemseite.
- Optionaler Fallback über `vcgencmd display_power`, wenn der Bildschirm kein
  HDMI-CEC unterstützt oder die CEC-Steuerung fehlschlägt.
- Separater validierender Root-Helfer mit systemd-Path und -Timer; die
  Webanwendung erhält keine allgemeinen Root- oder sudo-Rechte.

### Geändert

- Projektversion von `0.11.1` auf `0.11.2` erhöht.

## [0.11.1] – 2026-08-09

### Hinzugefügt

- Freitext-Inhalte unterstützen neben Bildern auch MP4- und WebM-Videos als
  automatisch stumm und in Schleife abgespielten Hintergrund, sowohl per Upload
  als auch aus der Mediathek.

### Geändert

- Die Playlist steht auf der Inhaltsseite an erster Stelle. Ein Auswahlfeld
  blendet anschließend nur das Formular für den gewünschten neuen Inhalt ein,
  wodurch die Seite deutlich kompakter bleibt.
- Die bisher missverständliche Aktion „In MP4 konvertieren“ heißt nun „Optimal
  konvertieren“ und zeigt während sowie nach der Verarbeitung einen sichtbaren
  Status.
- Projektversion von `0.11.0` auf `0.11.1` erhöht.

### Behoben

- Video-Vorschauen in der Mediathek verwenden wieder die Videodatei als Quelle
  und das Thumbnail nur als Poster. Zuvor wurde das JPG-Vorschaubild irrtümlich
  als Videoquelle geladen.
- Die Freitext-Vorschau zeigt bei einem nicht abspielbaren Videocodec einen
  verständlichen Hinweis zur optimalen Konvertierung.
- Wiederholte Videokonvertierungen entfernen die vorherige konvertierte Datei.

## [0.11.0] – 2026-08-09

### Hinzugefügt

- Lokaler Player-Cache mit Wiederaufnahme des zuletzt gezeigten Inhalts bei
  vorübergehend nicht erreichbarem Server sowie automatisches Überspringen
  defekter Bild- und Videodateien.
- Speicherübersicht und sichere Bereinigung ungenutzter Mediathek-Einträge.
- Zeitpläne für ganze Playlists nach Gültigkeitszeitraum, Wochentagen und
  täglichen Uhrzeiten; aktive Zeitpläne übersteuern die manuelle Auswahl.
- Geschützte Systemaktionen zum Neustart des Dienstes, Neustarten und
  Herunterfahren des Raspberry Pi über einen systemd-Helfer.
- Stabile Geräte-ID sowie Rollen Standalone, Master und Slave mit Master-Adresse
  und vorbereitetem Synchronisationsstatus.

### Geändert

- Projektversion von `0.10.0` auf `0.11.0` erhöht.

## [0.10.0] – 2026-08-08

### Hinzugefügt

- Responsive Verwaltungsoberfläche für Smartphones und Tablets mit
  einspaltigen Formularen, Mediathek-, Monitoring- und Playlist-Ansichten.
- Smartphone-gerechte Navigation, Touch-Ziele, Dialoggrößen und Aktionsleisten
  bis zu einer Bildschirmbreite von 320 Pixeln.

### Geändert

- Projektversion von `0.9.9` auf `0.10.0` erhöht.

## [0.9.9] – 2026-08-08

### Hinzugefügt

- Bilder und Videos aus dem direkten Inhalts-Upload werden automatisch in die
  Mediathek übernommen und mit ihrem Playlist-Eintrag verknüpft.
- Hochgeladene Videos können wahlweise mit oder ohne Ton wiedergegeben werden.
- Videos lassen sich unabhängig von der eingestellten Anzeigedauer vollständig
  bis zum Ende abspielen. Die Optionen stehen beim Upload, in der Mediathek und
  direkt an bestehenden Playlist-Einträgen zur Verfügung.

### Geändert

- Projektversion von `0.9.8` auf `0.9.9` erhöht.

## [0.9.8] – 2026-08-08

### Hinzugefügt

- Player-Heartbeat mit Online-/Offline-Erkennung, Wiedergabezustand, aktuell
  angezeigtem Inhalt und letztem Kontakt.
- Zentrale Monitoring-Karte auf der Systemseite mit freiem Speicher,
  CPU-Temperatur, Anwendungs- und Systemupdatezustand.
- Sichtbare Warnungen bei weniger als 10 % freiem Speicher oder mindestens
  80 °C CPU-Temperatur.
- Persistentes Protokoll der letzten 20 unterschiedlichen Playerfehler.

### Geändert

- Player- und Monitoringstatus werden auf der geöffneten Systemseite alle fünf
  Sekunden aktualisiert.
- Projektversion von `0.9.7` auf `0.9.8` erhöht.

## [0.9.7] – 2026-08-08

### Hinzugefügt

- Suche sowie Filter nach Medientyp, Kategorie und Nutzungszustand in der
  Mediathek.
- Umbenennen, Kategorien, Auflösung, Videodauer und Nutzungsanzahl je Medium.
- Mehrfachauswahl und gemeinsames Hinzufügen von bis zu 500 Medien zur aktiven
  Playlist.
- Automatische Video-Thumbnails und Metadaten zu Auflösung sowie Video- und
  Audio-Codec.
- Manuelle Konvertierung von Videos nach MP4 mit H.264/AAC und für Streaming
  optimierter Dateistruktur.

### Geändert

- Medienkarten verwenden kleine Thumbnail-Dateien statt der vollständigen
  Player-Dateien.
- Projektversion von `0.9.6` auf `0.9.7` erhöht.

## [0.9.6] – 2026-08-08

### Hinzugefügt

- Verlustarme Bildbearbeitung in der Mediathek mit 90°-Drehungen,
  16:9-Zuschnitt, Fokuspunkt, Helligkeit und Kontrast.
- Automatische Erzeugung einer auf Full HD begrenzten Player-Datei und eines
  kleinen Vorschaubildes über FFmpeg.
- Unveränderte Aufbewahrung des Originals als Ausgangspunkt für spätere
  Bearbeitungen ohne kumulativen Qualitätsverlust.

### Geändert

- Bereits in Playlists oder Freitext verwendete Mediathek-Bilder werden nach
  einer Bearbeitung automatisch auf die neue optimierte Datei umgestellt.
- Projektversion von `0.9.5` auf `0.9.6` erhöht.

## [0.9.5] – 2026-08-08

### Hinzugefügt

- Erweiterte Freitext-Gestaltung mit horizontaler und vertikaler Position,
  Text- und Akzentfarbe, drei Schriftgrößen und drei Schriftfamilien.
- Einstellbare Hintergrundabdunklung und horizontaler sowie vertikaler
  Bildfokus.
- Optionaler Logo-Upload mit automatischer Dateibereinigung beim Ersetzen oder
  Löschen des Freitext-Inhalts.
- Wiederverwendbare Gestaltungsvorlagen „Standard“, „Elegant“ und
  „Hinweis / Warnung“.

### Geändert

- Vorschau und Player verwenden für alle Freitext-Gestaltungsoptionen dasselbe
  Rendering.
- Projektversion von `0.9.4` auf `0.9.5` erhöht.

## [0.9.4] – 2026-08-08

### Hinzugefügt

- Verwaltung mehrerer voneinander getrennter Playlists mit Inhaltsanzahl,
  Aktivierung und sicherem Löschen inaktiver Playlists.
- Sofortige Umschaltung der aktiven Playlist für den Vollbild-Player.

### Geändert

- Bestehende Inhalte werden bei der Migration automatisch der Playlist
  „Standard“ zugeordnet.
- Neue Inhalte und Mediathek-Übernahmen landen in der jeweils aktiven Playlist.
- Projektversion von `0.9.3` auf `0.9.4` erhöht.

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
