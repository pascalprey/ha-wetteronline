# WetterOnline für Home Assistant (inoffiziell)

Eine **inoffizielle** Custom Integration, die die Wetterdaten der öffentlichen
Ortsseite von [wetteronline.de](https://www.wetteronline.de) ausliest und als
`weather`-Entität samt zusätzlicher Sensoren in Home Assistant bereitstellt.

Anders als die meisten existierenden WetterOnline-Integrationen (die nur die
RegenRadar-Karte einbinden) liefert diese Integration die **vollständigen**
Vorhersagedaten: aktuelle Lage, 48 Stunden stündlich und bis zu 16 Tage.

> [!WARNING]
> **Inoffiziell & ohne Gewähr.** Dieses Projekt steht in keiner Verbindung zur
> WetterOnline GmbH. Es liest die öffentlich erreichbare Webseite (Scraping).
> WetterOnline bietet keine freie API; die Inhalte sind urheberrechtlich
> geschützt. Nutze die Integration ausschließlich **privat**, mit niedriger
> Abruffrequenz, und verbreite die Daten/Bilder nicht weiter. Bei jeder
> Layout-Änderung der Seite kann das Parsen brechen. Wer eine rechtlich saubere,
> stabile Quelle für Deutschland möchte, ist mit dem **DWD** (Deutscher
> Wetterdienst, Open Data) oder **Open‑Meteo** besser bedient.

## Funktionen

- **`weather.<ort>`-Entität** mit aktuellen Werten und Vorhersagen:
  - aktuell: Temperatur, gefühlte Temperatur, Taupunkt, Luftfeuchte, Luftdruck,
    Wind/Böen/Richtung, Sichtweite, UV-Index, Zustand
  - **stündlich** (~48 h) und **täglich** (bis 14 Tage), jeweils mit Temperatur,
    gefühlter Temperatur, Feuchte, Druck, Wind/Böen, Regenwahrscheinlichkeit,
    Niederschlagsmenge (mm, täglich) und UV-Index (täglich)
- **Zusätzliche Sensoren** je Ort:
  - Temperatur, gefühlte Temperatur, Taupunkt, Luftfeuchte, Luftdruck,
    Wind/Böen/Richtung, Sichtweite, UV-Index, Regenwahrscheinlichkeit
  - Sonnenaufgang/-untergang, Sonnenstunden heute, Höchst-/Tiefsttemperatur heute,
    Niederschlag heute
  - **Pollenflug** (14 Allergene, Belastung 0–3, 7-Tage-Vorhersage als Attribut)
  - **Unwetterwarnungen** (Anzahl + Details als Attribut)
  - optional (standardmäßig deaktiviert): Sonnenstand, Luftdrucktendenz,
    Smog-Level, Tageslänge, Mondphase, Mondauf-/-untergang

## Datenquelle & Grenzen

Die Daten stammen aus der server-seitig gerenderten Seite
`https://www.wetteronline.de/wetter/<ort>`, genauer aus dem darin eingebetteten
Angular-State (`ng-state`), der die Antworten von WetterOnlines Backend-API
spiegelt – ein einziger GET liefert alles. **Nicht enthalten:** ein numerischer
Bewölkungsgrad (%) gibt es im Datensatz nicht (nur Zustand/Symbol und
Sonnenstunden). Stündliche Niederschlagsmenge in mm ist ebenfalls nicht
verfügbar (nur tägliche).

## Installation

### HACS (empfohlen)

1. HACS → ⋮ → *Benutzerdefinierte Repositories* → dieses Repo als
   *Integration* hinzufügen.
2. „WetterOnline" installieren, Home Assistant neu starten.

### Manuell

`custom_components/wetteronline/` in den `config/custom_components/`-Ordner der
Home-Assistant-Installation kopieren und neu starten.

## Einrichtung

*Einstellungen → Geräte & Dienste → Integration hinzufügen → „WetterOnline"*,
dann einen Ort eingeben (z. B. „Köln"). Mehrere Orte können einzeln hinzugefügt
werden. Das Abrufintervall ist über *Konfigurieren* einstellbar (Standard 30 min,
Minimum 10 min).

## Entwicklung

Der Parser (`custom_components/wetteronline/api.py`) ist bewusst frei von
Home-Assistant-Importen und lässt sich offline gegen eine gespeicherte HTML-Seite
testen (siehe `tests/`).

## Lizenz

MIT – siehe [LICENSE](LICENSE).
