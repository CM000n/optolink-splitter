ERROR importing settings module: No module named 'settings_ini'
# Entities of the Vitotronic 200 (VScotHO1) integration

Generated from `homeassistant_poll_list.py` (source *splitter*) and `extras/vito_extras.py` (source *extras*) by `tools/entity_doc.py`.
115 entities in 9 devices. Entity ids are `<domain>.vito_<name>`; the display names are German like in
Home Assistant. Home Assistant sorts the entities of a device by category (controls, sensors, configuration, diagnostic) and then by name.

## Viessmann Heizung

| Entity | Name | Category | Source |
|---|---|---|---|
| `button.vito_forcepoll` | Alle Werte neu lesen | diagnostic | splitter |

## Heizung Anlage

| Entity | Name | Category | Source |
|---|---|---|---|
| `binary_sensor.vito_sammelstoerung` | Sammelstörung | primary | splitter |
| `binary_sensor.vito_urlaubsprogramm` | Urlaubsprogramm | primary | extras |
| `button.vito_urlaubsprogramm_beenden` | Urlaubsprogramm beenden | primary | extras |
| `sensor.vito_aussentemperatur` | Außentemperatur | primary | splitter |
| `sensor.vito_urlaubsprogramm_beginn` | Urlaubsprogramm Beginn | primary | splitter |
| `sensor.vito_urlaubsprogramm_ende` | Urlaubsprogramm Ende | primary | splitter |
| `binary_sensor.vito_anlagenzeit_abweichung` | Anlagenzeit weicht ab | diagnostic | splitter |
| `binary_sensor.vito_aussentemperatur_sensorfehler` | Außentemperatur Sensorfehler | diagnostic | splitter |
| `sensor.vito_aussentemperatur_gedaempft` | Außentemperatur gedämpft | diagnostic | splitter |
| `sensor.vito_aussentemperatur_gefiltert` | Außentemperatur gefiltert | diagnostic | splitter |
| `sensor.vito_aussentemperatur_gemischt` | Außentemperatur gemischt (Regelung) | diagnostic | splitter |
| `sensor.vito_fehlerhistorie` | Letzter Fehler | diagnostic | extras |
| `sensor.vito_regler_seriennummer` | Regler Seriennummer | diagnostic | splitter |

## Heizung Kessel

| Entity | Name | Category | Source |
|---|---|---|---|
| `binary_sensor.vito_interne_kesselpumpe` | Interne Kesselpumpe | primary | splitter |
| `sensor.vito_abgastemperatur` | Abgastemperatur | primary | splitter |
| `sensor.vito_kesseltemperatur` | Kesseltemperatur | primary | splitter |
| `sensor.vito_kesselsolltemperatur` | Solltemperatur | primary | splitter |
| `binary_sensor.vito_kesseltemperatur_sensorfehler` | Temperatur Sensorfehler | diagnostic | splitter |
| `sensor.vito_interne_kesselpumpe_laufzeit_heute` | Interne Kesselpumpe Laufzeit heute | diagnostic | extras |

## Heizung Brenner

| Entity | Name | Category | Source |
|---|---|---|---|
| `binary_sensor.vito_brenner_aktiv` | Aktiv | primary | splitter |
| `binary_sensor.vito_brenner_taktung` | Taktung | primary | extras |
| `sensor.vito_brenner_laufzeit_heute` | Laufzeit heute | primary | extras |
| `sensor.vito_brennermodulation` | Modulation | primary | splitter |
| `sensor.vito_brenner_starts_heute` | Starts heute | primary | extras |
| `sensor.vito_brenner_automatik` | Automatik | diagnostic | extras |
| `sensor.vito_brenner_automatik_fehlercode` | Automatik Fehlercode | diagnostic | extras |
| `sensor.vito_brenner_automatik_fehlerdetails` | Automatik Fehlerdetails | diagnostic | extras |
| `sensor.vito_brennerlaufzeit` | Betriebsstunden | diagnostic | splitter |
| `sensor.vito_brenner_fehlerstatus` | Fehlerstatus | diagnostic | extras |
| `sensor.vito_brenner_fehlerstatus_fehlercode` | Fehlerstatus Fehlercode | diagnostic | extras |
| `sensor.vito_brenner_fehlerstatus_fehlerdetails` | Fehlerstatus Fehlerdetails | diagnostic | extras |
| `sensor.vito_brenner_letzte_laufzeit` | Letzte Laufzeit | diagnostic | extras |
| `sensor.vito_brenner_letzte_pause` | Letzte Pause | diagnostic | extras |
| `sensor.vito_brennerstarts` | Starts gesamt | diagnostic | splitter |
| `sensor.vito_brenner_starts_letzte_stunde` | Starts letzte Stunde | diagnostic | extras |
| `sensor.vito_brenner_laufzeit_pro_start` | Ø Laufzeit pro Start | diagnostic | extras |

## Heizung Warmwasser

| Entity | Name | Category | Source |
|---|---|---|---|
| `binary_sensor.vito_warmwasser_aufladung` | Aufladung | primary | splitter |
| `binary_sensor.vito_warmwasser_ladepumpe` | Ladepumpe | primary | splitter |
| `binary_sensor.vito_warmwasser_zeitprogramm_aktiv` | Zeitprogramm | primary | extras |
| `button.vito_warmwasser_boost` | Zusatzaufheizung starten | primary | extras |
| `button.vito_warmwasser_zeitprogramm_zuruecksetzen` | Überbrückung beenden | primary | extras |
| `number.vito_warmwasser_solltemperatur` | Solltemperatur | primary | splitter |
| `sensor.vito_warmwasser_speichertemperatur` | Speichertemperatur | primary | splitter |
| `switch.vito_warmwasser_dauerbetrieb` | Dauerbetrieb (Zeitprogramm überbrückt) | primary | extras |
| `water_heater.vito_warmwasser` | (device name) | primary | splitter |
| `number.vito_warmwasser_boost_dauer` | Dauer Zusatzaufheizung | config | extras |
| `binary_sensor.vito_warmwasser_auslauftemperatur_sensorfehler` | Auslauftemperatur Sensorfehler | diagnostic | splitter |
| `binary_sensor.vito_warmwasser_speichertemperatur_sensorfehler` | Speichertemperatur Sensorfehler | diagnostic | splitter |
| `sensor.vito_warmwasser_ladepumpe_laufzeit_heute` | Ladepumpe Laufzeit heute | diagnostic | extras |
| `sensor.vito_warmwasser_zeitprogramm` | Zeitplan (aktuell) | diagnostic | extras |

## Heizung Zirkulation

| Entity | Name | Category | Source |
|---|---|---|---|
| `binary_sensor.vito_zirkulationspumpe` | WW-Zirkulationspumpe | primary | splitter |
| `binary_sensor.vito_zirkulation_zeitprogramm_aktiv` | Zeitprogramm | primary | extras |
| `button.vito_zirkulation_boost` | Zusatzlauf starten | primary | extras |
| `button.vito_zirkulation_zeitprogramm_zuruecksetzen` | Überbrückung beenden | primary | extras |
| `switch.vito_zirkulation_dauerbetrieb` | Dauerbetrieb (Zeitprogramm überbrückt) | primary | extras |
| `number.vito_zirkulation_boost_dauer` | Dauer Zusatzlauf | config | extras |
| `sensor.vito_zirkulationspumpe_laufzeit_heute` | Pumpe Laufzeit heute | diagnostic | extras |
| `sensor.vito_zirkulation_zeitprogramm` | Zeitplan (aktuell) | diagnostic | extras |

## Heizung Solar

| Entity | Name | Category | Source |
|---|---|---|---|
| `binary_sensor.vito_solar_nachladeunterdrueckung` | Nachladeunterdrückung | primary | splitter |
| `binary_sensor.vito_solarpumpe` | Solarpumpe | primary | splitter |
| `sensor.vito_solarertrag_gestern` | Ertrag gestern | primary | splitter |
| `sensor.vito_solarertrag_heute` | Ertrag heute | primary | splitter |
| `sensor.vito_solarertrag_letzte_7_tage` | Ertrag letzte 7 Tage | primary | splitter |
| `sensor.vito_solar_gesamtertrag` | Gesamtertrag | primary | splitter |
| `sensor.vito_solar_kollektortemperatur` | Solarkollektor-Temperatur | primary | splitter |
| `sensor.vito_solar_speichertemperatur` | Solarspeicher-Temperatur | primary | splitter |
| `sensor.vito_solar_temperaturdifferenz_kollektor_speicher` | Temperaturdifferenz Kollektor/Speicher | primary | extras |
| `binary_sensor.vito_solar_kollektortemperatur_sensorfehler` | Kollektortemperatur Sensorfehler | diagnostic | splitter |
| `binary_sensor.vito_solar_speichertemperatur_sensorfehler` | Speichertemperatur Sensorfehler | diagnostic | splitter |
| `sensor.vito_solarpumpe_laufzeit_heute` | Kreispumpe Laufzeit heute | diagnostic | extras |

## Heizkreis 1 (Fußbodenheizung)

| Entity | Name | Category | Source |
|---|---|---|---|
| `binary_sensor.vito_hk1_frostschutz` | Frostschutz | primary | splitter |
| `binary_sensor.vito_hk1_pumpe` | Umwälzpumpe | primary | splitter |
| `binary_sensor.vito_hk1_zeitprogramm_aktiv` | Zeitprogramm | primary | extras |
| `climate.vito_hk1_heizung` | (device name) | primary | splitter |
| `number.vito_hk1_komforttemperatur` | Solltemperatur Komfort | primary | splitter |
| `number.vito_hk1_normaltemperatur` | Solltemperatur Normal | primary | splitter |
| `number.vito_hk1_reduzierte_temperatur` | Solltemperatur Reduziert | primary | splitter |
| `select.vito_hk1_betriebsart` | Betriebsart | primary | splitter |
| `sensor.vito_hk1_programm` | Aktiver Heizmodus | primary | extras |
| `sensor.vito_hk1_raumsolltemperatur_aktuell` | Raum-Solltemperatur aktuell | primary | splitter |
| `sensor.vito_hk1_vorlauftemperatur` | Vorlauftemperatur | primary | splitter |
| `switch.vito_hk1_komfortbetrieb` | Komfortbetrieb | primary | extras |
| `switch.vito_hk1_sparbetrieb` | Sparbetrieb | primary | extras |
| `number.vito_hk1_heizkurve_steigung` | Heizkurve Steigung | config | splitter |
| `number.vito_hk1_heizkurve_niveau` | Heizkurve Verschiebung | config | splitter |
| `text.vito_hk1_name` | Name | config | extras |
| `binary_sensor.vito_hk1_vorlauftemperatur_sensorfehler` | Vorlauftemperatur Sensorfehler | diagnostic | splitter |
| `sensor.vito_hk1_pumpe_laufzeit_heute` | Umwälzpumpe Laufzeit heute | diagnostic | extras |
| `sensor.vito_hk1_vorlauf_abweichung_zur_heizkurve` | Vorlauf Abweichung (Heizkurve) | diagnostic | extras |
| `sensor.vito_hk1_soll_vorlauftemperatur_heizkurve` | Vorlauf Soll (Heizkurve) | diagnostic | extras |
| `sensor.vito_hk1_vorlaufsolltemperatur` | Vorlauf Soll (Regler) | diagnostic | splitter |
| `sensor.vito_hk1_zeitprogramm` | Zeitplan (aktuelle Phase) | diagnostic | extras |

## Heizkreis 2 (Heizkörper)

| Entity | Name | Category | Source |
|---|---|---|---|
| `binary_sensor.vito_hk2_frostschutz` | Frostschutz | primary | splitter |
| `binary_sensor.vito_hk2_pumpe` | Umwälzpumpe | primary | splitter |
| `binary_sensor.vito_hk2_zeitprogramm_aktiv` | Zeitprogramm | primary | extras |
| `climate.vito_hk2_heizung` | (device name) | primary | splitter |
| `number.vito_hk2_komforttemperatur` | Solltemperatur Komfort | primary | splitter |
| `number.vito_hk2_normaltemperatur` | Solltemperatur Normal | primary | splitter |
| `number.vito_hk2_reduzierte_temperatur` | Solltemperatur Reduziert | primary | splitter |
| `select.vito_hk2_betriebsart` | Betriebsart | primary | splitter |
| `sensor.vito_hk2_programm` | Aktiver Heizmodus | primary | extras |
| `sensor.vito_hk2_raumsolltemperatur_aktuell` | Raum-Solltemperatur aktuell | primary | splitter |
| `sensor.vito_hk2_vorlauftemperatur` | Vorlauftemperatur | primary | splitter |
| `switch.vito_hk2_komfortbetrieb` | Komfortbetrieb | primary | extras |
| `switch.vito_hk2_sparbetrieb` | Sparbetrieb | primary | extras |
| `number.vito_hk2_heizkurve_steigung` | Heizkurve Steigung | config | splitter |
| `number.vito_hk2_heizkurve_niveau` | Heizkurve Verschiebung | config | splitter |
| `text.vito_hk2_name` | Name | config | extras |
| `binary_sensor.vito_hk2_vorlauftemperatur_sensorfehler` | Vorlauftemperatur Sensorfehler | diagnostic | splitter |
| `sensor.vito_hk2_pumpe_laufzeit_heute` | Umwälzpumpe Laufzeit heute | diagnostic | extras |
| `sensor.vito_hk2_vorlauf_abweichung_zur_heizkurve` | Vorlauf Abweichung (Heizkurve) | diagnostic | extras |
| `sensor.vito_hk2_soll_vorlauftemperatur_heizkurve` | Vorlauf Soll (Heizkurve) | diagnostic | extras |
| `sensor.vito_hk2_vorlaufsolltemperatur` | Vorlauf Soll (Regler) | diagnostic | splitter |
| `sensor.vito_hk2_zeitprogramm` | Zeitplan (aktuelle Phase) | diagnostic | extras |

## Data points without an entity

Published on MQTT (`<topic>/<name>`), consumed by `extras/vito_extras.py` or kept for diagnostics.

| Data point | Name |
|---|---|
| `hk1_betriebsprogramm_roh` | Betriebsprogramm (Rohwert) |
| `hk1_partybetrieb` | Komfortbetrieb (Status) |
| `hk1_programm` | Programm (Phase, Rohwert) |
| `hk1_sparbetrieb` | Sparbetrieb (Status) |
| `hk1_zeitprogramm_roh_1` | Zeitprogramm (Rohdaten 1) |
| `hk1_zeitprogramm_roh_2` | Zeitprogramm (Rohdaten 2) |
| `hk2_betriebsprogramm_roh` | Betriebsprogramm (Rohwert) |
| `hk2_partybetrieb` | Komfortbetrieb (Status) |
| `hk2_programm` | Programm (Phase, Rohwert) |
| `hk2_sparbetrieb` | Sparbetrieb (Status) |
| `hk2_zeitprogramm_roh_1` | Zeitprogramm (Rohdaten 1) |
| `hk2_zeitprogramm_roh_2` | Zeitprogramm (Rohdaten 2) |
| `solarertrag_tageswerte_roh` | Solarertrag Tageswerte (Rohdaten) |
| `warmwasser_zeitprogramm_roh_1` | Zeitprogramm (Rohdaten 1) |
| `warmwasser_zeitprogramm_roh_2` | Zeitprogramm (Rohdaten 2) |
| `zirkulation_zeitprogramm_roh_1` | Zeitprogramm (Rohdaten 1) |
| `zirkulation_zeitprogramm_roh_2` | Zeitprogramm (Rohdaten 2) |
