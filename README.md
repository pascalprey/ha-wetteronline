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

- **`weather.<ort>`-Entität** mit:
  - aktueller Temperatur, Zustand und Windrichtung
  - **stündlicher** Vorhersage (~48 h): Temperatur, Zustand, Regenwahrscheinlichkeit
  - **täglicher** Vorhersage (bis 16 Tage): Max/Min-Temperatur, Zustand,
    Regenwahrscheinlichkeit, Niederschlagsmenge (mm), Wind & Böen
- **Zusätzliche Sensoren** je Ort:
  - Temperatur, Windrichtung
  - Sonnenaufgang / Sonnenuntergang (Zeitstempel), Sonnenstand (°)
  - Höchst-/Tiefsttemperatur heute, Niederschlag heute (mm),
    Regenwahrscheinlichkeit heute, Sonnenstunden heute, Windböen heute

## Datenquelle & Grenzen

Die Daten stammen aus der server-seitig gerenderten Seite
`https://www.wetteronline.de/wetter/<ort>`. Auf der **freien** Seite gibt es
**keine** Werte für Luftfeuchte, Luftdruck, gefühlte Temperatur oder UV-Index –
diese sind daher nicht enthalten. Die stündliche Vorhersage enthält keine
Windrichtung (nur die tägliche).

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
