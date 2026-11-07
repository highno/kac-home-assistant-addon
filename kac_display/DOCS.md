# KAC Display Bridge – Installation und Konfiguration

## Ergebnis und Voraussetzungen

Dieses Add-on liest frei auswählbare Home-Assistant-Entitäten, formatiert sie zu KAC-Seiten und sendet die Seiten regelmäßig an ein oder mehrere KAC-Geräte. Unterstützt werden alle derzeit dokumentierten Zeilentypen, Teilübertragung großer Seitensätze und die KAC-Bild-Slots.

Voraussetzungen:

- Home Assistant OS oder eine andere Installation mit Supervisor/App-Unterstützung.
- Ein GeekMagic SmallTV Ultra mit installierter KleinerAnzeigeComputer-Firmware.
- IP-Adresse oder Hostname und Geräteschlüssel des KAC. Der Schlüssel steht auf der eingebauten **Device**-Seite und der KAC-Einrichtungsseite.
- Für `big`, `sparkline` und fünf Bild-Slots wird KAC 0.8.10 oder neuer benötigt. Bei der Recherche am 7. November 2026 war 0.8.11 das veröffentlichte Firmware-Image.

## Installation

### Als eigenes Git-Repository

1. In Home Assistant **Einstellungen → Apps → App installieren → Repositories** öffnen.
2. `https://github.com/highno/kac-home-assistant-addon` als Repository hinzufügen.
3. Alternativ den Installationsbutton in der Repository-README verwenden.
4. **KAC Display Bridge** auswählen und installieren.
5. Das Add-on einmal starten. Es legt `kac.yaml` im eigenen App-Konfigurationsordner an und beendet sich mit einer verständlichen Meldung.
6. Die Datei `app_configs/<App-ID>/kac.yaml` mit File Editor, Samba oder SSH bearbeiten. Danach das Add-on neu starten.

Für eine rein lokale Installation kann der Ordner `kac_display` in den lokalen Apps/Add-ons-Ordner der Home-Assistant-Installation kopiert und der App Store neu geladen werden.

## Add-on-Optionen

| Option | Standard | Bedeutung |
|---|---:|---|
| `config_file` | `/config/kac.yaml` | Ausführliche YAML-Konfiguration im eigenen App-Konfigurationsordner |
| `log_level` | `info` | `debug`, `info`, `warning` oder `error` |
| `dry_run` | `false` | Seiten nur erzeugen/protokollieren, nichts an KAC senden |

Geänderte Optionen oder eine geänderte `kac.yaml` werden nach einem Neustart des Add-ons eingelesen.

## Schnellstart

Die automatisch erzeugte Datei entspricht `examples/kac.yaml`. Mindestens diese Werte müssen angepasst werden:

```yaml
entities:
  temperature: sensor.living_room_temperature

formats:
  temperature: "{{ value | float(0) | round(1) }} °C"

devices:
  - name: living_room
    host: 192.168.1.50
    key: CHANGE-ME
    pages:
      - title: Home
        rows:
          - type: big
            label: Temperature
            entity: temperature
            format: temperature
    images: []
```

Der Geräteschlüssel darf alternativ in einer separaten Datei liegen:

```yaml
key_file: secrets/living-room-kac.key
```

Relative Pfade werden relativ zu `kac.yaml` aufgelöst. Der Schlüssel muss gemäß KAC-Dokumentation 1–32 druckbare ASCII-Zeichen ohne Leerzeichen enthalten.

## Entitäten und Vorlagen

`entities` ordnet frei gewählte Aliase Home-Assistant-`entity_id`s zu. Eine Zeile wählt mit `entity` einen Alias aus. In Vorlagen stehen dann zur Verfügung:

- `value`: der Zustand als Zeichenkette;
- `attributes`: das Attribut-Dictionary der ausgewählten Entität;
- `entity`: Objekt mit `entity_id`, `state`, `attributes`, `available`, `last_changed`, `last_updated`;
- `entities` und `states`: Mapping aller konfigurierten Aliase auf diese Objekte;
- `available`: `false` bei `unknown` oder `unavailable`.

Beispiele:

```yaml
value: "{{ value | float(0) | round(1) }} °C"
alert: "{{ value | float(0) > 28 }}"
value: "{{ attributes.get('friendly_name', entity.entity_id) }}"
value: "{{ entities.battery.state }} %"
```

`formats` sind benannte Vorlagen für das Feld `value`. In einer Zeile darf entweder `format` oder eine direkte `value`-Vorlage stehen. Die Vorlagen laufen in einer eingeschränkten Jinja-Umgebung; es handelt sich bewusst **nicht** um die vollständige Home-Assistant-Template-Umgebung. Funktionen wie `states()` oder `now()` aus Home Assistant sind daher nicht vorhanden.

## KAC-Seiten und Zeilentypen

Eine Textseite hat einen Titel und höchstens acht Zeilen. Freundliche Typnamen und ihre dokumentierten KAC-Codes:

| Konfiguration | KAC-Code | Felder | Darstellung |
|---|---:|---|---|
| `heading` | `h` | `label`, `value`, `alert` | orange Überschrift, Wert rechts |
| `value` | `k` | `label`, `value`, `alert` | graues Label, Wert rechts |
| `down` | `d` | `percent`, `value`, `alert` | blauer Abwärtspfeil und Balken |
| `up` | `u` | `percent`, `value`, `alert` | oranger Aufwärtspfeil und Balken |
| `bar` | `b` | `label`, `percent`, `value`, `alert` | beschrifteter blauer Balken |
| `big` | `g` | `label`, `value`, `alert` | großer, fetter Wert |
| `sparkline` | `s` | `label`, Entität/`values`, `value`, `alert` | bis zu 20 Verlaufsspalten |
| `empty` | `-` | keine | Leerzeile |

Die dokumentierten KAC-Felder werden ohne Erweiterung übertragen: Seitentitel `t`, Zeilen `z`, Typ `y`, Label `l`, Wert `v`, Prozent `p`, Verlauf `w`, Alarm `a`.

`percent` kann Zahl oder Vorlage sein und wird auf 0–100 begrenzt. Fehlt `percent` bei Balken, wird der Zustand der ausgewählten Entität benutzt. `alert` akzeptiert Boolean oder eine Vorlage und setzt bei wahr `a: 1`.

### Sparkline

Mit `entity` sammelt das Add-on bei jedem Aktualisierungszyklus einen numerischen Wert und bewahrt bis zu 20 Punkte in `/data` auf:

```yaml
- type: sparkline
  label: Power
  entity: power
  value: "{{ value }} W"
  history_points: 20
  scale_min: 0
  scale_max: 5000
```

Alternativ kann eine feste Liste angegeben werden:

```yaml
- type: sparkline
  label: Test
  value: 70 %
  values: [10, 30, 25, 60, 45, 80, 70]
  scale_min: 0
  scale_max: 100
```

## Geräteeinstellungen

Unter `settings` werden nur dokumentierte KAC-Felder angeboten:

```yaml
settings:
  rotation_seconds: 20       # KAC rot, 5..255
  brightness: 80             # optionales Dashboard-Override b, 0..100
  timezone: CET-1CEST,M3.5.0,M10.5.0/3
  brightness_schedule:
    day: 90                  # hell_tag
    night: 10                # hell_nacht
    night_from: 23           # nacht_von
    night_until: 7           # nacht_bis
```

KAC wählt die sichtbare Seite selbst anhand von Uhrzeit, Rotationsintervall und Seitenzahl aus. Das Add-on sendet immer den vollständigen Textseitensatz. Wird der JSON-Inhalt zu groß, nutzt es automatisch die dokumentierten Felder `ab` und `gesamt`; jede Anfrage bleibt mit Sicherheitsreserve unter dem KAC-Limit von 4096 Byte.

## Bilder

KAC-Bilder sind eigenständige Vollbildseiten. Sie können nicht mit Textzeilen kombiniert werden.

```yaml
images:
  - slot: 1
    source: images/photo.png
    fit: contain
    upload: on_change
    quality: 90

  - slot: 2
    source: images/weather.gif
    fit: cover
    gif_colors: 64
    gif_min_delay_ms: 100

  - slot: 5
    delete: true
```

- `slot`: 1–5.
- `fit: cover`: mittiger quadratischer Ausschnitt; `contain`: ganzes Bild mit schwarzen Rändern.
- `upload: on_change`: nur nach Datei-/Optionsänderung; `startup`: bei jedem Add-on-Start.
- Statische Eingaben werden als 240×240 Baseline-JPG erzeugt.
- Animierte Eingaben werden als 240×240 GIF mit gemeinsamer Palette erzeugt.
- Das vorbereitete Ergebnis darf höchstens 1 MB groß sein.
- KAC erlaubt insgesamt nur ein GIF. Ein GIF reserviert laut Firmware-Dokumentation etwa 23,7 KB RAM und reduziert die Zahl möglicher Textseiten deutlich.

Das Add-on lädt keine Bilder aus Home-Assistant-Kamera-/Media-Entitäten oder URLs. Diese Version verarbeitet absichtlich nur lokale Dateien im App-Konfigurationsordner.

## Text- und Firmwaregrenzen

- KAC zeigt druckbares ASCII sowie `°`. Im Standardmodus werden deutsche Umlaute transliteriert (`ä` → `ae`) und andere nicht unterstützte Zeichen zu `?`. `text_mode: strict` bricht stattdessen mit einem Fehler ab.
- Titel werden auf 15 UTF-8-Byte, Labels/Werte auf 27 Byte und Sparkline-Labels auf 7 Byte begrenzt.
- Die tatsächliche Seitenzahl hängt vom freien RAM des Geräts ab (typisch etwa 25–28 volle Seiten ohne GIF). Das Add-on wertet die KAC-Antwort `voll: true` aus, kann die verfügbare Zahl aber nicht vorhersagen.
- Nach drei Minuten ohne neue Daten zeigt KAC einen roten Statuspunkt; nach zehn Minuten zeigt die Firmware ihre eingebauten Device-/Guide-Seiten statt veralteter Dashboardwerte. Daher sollte `update_interval_seconds` deutlich unter 180 bleiben.

## Sicherheit

- Die KAC-Schnittstelle verwendet dokumentiert nur unverschlüsseltes HTTP. Geräteschlüssel und Messwerte sind im lokalen Netz nicht transportverschlüsselt. KAC empfiehlt ein getrenntes IoT-Netz/VLAN.
- `homeassistant_api: true` gibt einem Add-on über den Supervisor-Proxy Administratorrechte. Dieser Quellcode verwendet den Token ausschließlich für `GET /states`, aber der Token selbst ist entsprechend sensibel.
- Schlüssel werden weder in normale Logs noch in gerenderte Seiten geschrieben. `kac.yaml` und optionale Schlüsseldateien gehören trotzdem geschützt und nicht in ein öffentliches Repository.

## Offene bzw. bewusst nicht erfundene Punkte

1. Die KAC-Dokumentation beschreibt Bildseiten als zusätzliche Seiten am Ende der Rotation, legt aber die exakte Reihenfolge mehrerer belegter Slots nicht ausdrücklich als API-Vertrag fest. Das Add-on verwaltet Slotnummern, verspricht darüber hinaus keine Reihenfolge.
2. Eingebaute Device-/Guide-Seiten sind Firmwareverhalten und nicht per `/api/seiten` konfigurierbar.
3. Bilder und Messwertzeilen können laut dokumentiertem Modell nicht auf derselben Seite platziert werden.
4. KAC hat keine dokumentierte HTTPS-Schnittstelle, keine dokumentierte automatische Geräteerkennung und keine dokumentierte Push-Verbindung. Darum werden Host, Schlüssel und Aktualisierungsintervall explizit konfiguriert.
5. Das Add-on wurde offline gegen simulierte HTTP-Antworten getestet. Ein echter Hardware-End-to-End-Test benötigt ein erreichbares SmallTV-Ultra-Gerät mit KAC und bleibt vor der produktiven Nutzung erforderlich.

## Fehlerdiagnose

- **HTTP 403:** KAC-Geräteschlüssel falsch.
- **Gerät nicht erreichbar:** Host/IP, VLAN-Routing und Port 80 prüfen; ausdrücklich `http://`, nicht HTTPS.
- **Roter Punkt:** Add-on-Log prüfen; seit mehr als drei Minuten keine erfolgreiche Seitenaktualisierung.
- **Device/Guide statt eigener Seiten:** seit zehn Minuten keine Daten oder nie erfolgreich gesendet.
- **`voll: true`:** weniger Textseiten konfigurieren; insbesondere GIF entfernen/ersetzen.
- **Bild HTTP 422:** meist zweites GIF, progressives/ungeeignetes Bild oder Firmwarelimit. Das Add-on konvertiert Eingaben, meldet aber die konkrete Geräteantwort.
- **Vorlagenfehler:** `dry_run: true` aktivieren und Add-on-Log lesen.

## Verifizierte Quellen

- [Offizielle KAC-README und API-Dokumentation](https://github.com/GiT-BeDa/KleinerAnzeigeComputer)
- [Offizieller KAC-Changelog](https://github.com/GiT-BeDa/KleinerAnzeigeComputer/blob/main/CHANGELOG.md)
- [Offizielles KAC-Python-Hilfsmodul](https://github.com/GiT-BeDa/KleinerAnzeigeComputer/blob/main/tools/kac.py)
- [Home Assistant: App-Konfiguration](https://contributors.home-assistant.io/apps/reference/configuration/)
- [Home Assistant: Kommunikation mit Core/Supervisor](https://contributors.home-assistant.io/apps/guides/communication/)
- [Home Assistant: Repository erstellen und hinzufügen](https://contributors.home-assistant.io/apps/guides/repository/)
