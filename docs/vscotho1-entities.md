# Entities of the Vitotronic 200 (VScotHO1) integration

Generated from `homeassistant_poll_list.py` (source *splitter*) and `extras/vito_extras.py` (source *extras*).
135 entities in 8 devices. Entity ids are `<domain>.vito_<name>`; the display names are German like in Home Assistant.

## Viessmann Heizung

| Entity | Name | Source |
|---|---|---|
| `button.vito_forcepoll` | Alle Werte neu lesen | splitter |

## Heizung Anlage

| Entity | Name | Source |
|---|---|---|
| `binary_sensor.vito_anlagenzeit_abweichung` | Anlagenzeit weicht ab | splitter |
| `binary_sensor.vito_aussentemperatur_sensorfehler` | Außentemperatur Sensorfehler | splitter |
| `binary_sensor.vito_sammelstoerung` | Sammelstörung | splitter |
| `binary_sensor.vito_urlaubsprogramm` | Urlaubsprogramm | extras |
| `button.vito_urlaubsprogramm_beenden` | Urlaubsprogramm beenden | extras |
| `sensor.vito_aussentemperatur` | Außentemperatur | splitter |
| `sensor.vito_aussentemperatur_gedaempft` | Außentemperatur gedämpft | splitter |
| `sensor.vito_aussentemperatur_gefiltert` | Außentemperatur gefiltert | splitter |
| `sensor.vito_aussentemperatur_gemischt` | Außentemperatur gemischt (Regelung) | splitter |
| `sensor.vito_fehlerhistorie` | Letzter Fehler | extras |
| `sensor.vito_regler_seriennummer` | Regler Seriennummer | splitter |
| `sensor.vito_urlaubsprogramm_beginn` | Urlaubsprogramm Beginn | splitter |
| `sensor.vito_urlaubsprogramm_ende` | Urlaubsprogramm Ende | splitter |

## Heizung Kessel

| Entity | Name | Source |
|---|---|---|
| `binary_sensor.vito_brenner_aktiv` | Brenner | splitter |
| `binary_sensor.vito_brenner_taktung` | Brenner Taktung | extras |
| `binary_sensor.vito_interne_kesselpumpe` | Interne Kesselpumpe | splitter |
| `binary_sensor.vito_kesseltemperatur_sensorfehler` | Temperatur Sensorfehler | splitter |
| `sensor.vito_abgastemperatur` | Abgastemperatur | splitter |
| `sensor.vito_brenner_automatik` | Brenner Automatik | extras |
| `sensor.vito_brenner_automatik_fehlercode` | Brenner Automatik Fehlercode | extras |
| `sensor.vito_brenner_automatik_fehlerdetails` | Brenner Automatik Fehlerdetails | extras |
| `sensor.vito_brenner_fehlerstatus` | Brenner Fehlerstatus | extras |
| `sensor.vito_brenner_fehlerstatus_fehlercode` | Brenner Fehlerstatus Fehlercode | extras |
| `sensor.vito_brenner_fehlerstatus_fehlerdetails` | Brenner Fehlerstatus Fehlerdetails | extras |
| `sensor.vito_brenner_laufzeit_heute` | Brenner Laufzeit heute | extras |
| `sensor.vito_brenner_laufzeit_pro_start` | Brenner Ø Laufzeit pro Start | extras |
| `sensor.vito_brenner_letzte_laufzeit` | Brenner letzte Laufzeit | extras |
| `sensor.vito_brenner_letzte_pause` | Brenner letzte Pause | extras |
| `sensor.vito_brenner_starts_heute` | Brenner Starts heute | extras |
| `sensor.vito_brenner_starts_letzte_stunde` | Brenner Starts letzte Stunde | extras |
| `sensor.vito_brennerlaufzeit` | Brennerbetriebsstunden | splitter |
| `sensor.vito_brennermodulation` | Brennermodulation | splitter |
| `sensor.vito_brennerstarts` | Brennerstarts | splitter |
| `sensor.vito_interne_kesselpumpe_laufzeit_heute` | Interne Kesselpumpe Laufzeit heute | extras |
| `sensor.vito_kesselsolltemperatur` | Solltemperatur | splitter |
| `sensor.vito_kesseltemperatur` | Kesseltemperatur | splitter |

## Heizung Warmwasser

| Entity | Name | Source |
|---|---|---|
| `binary_sensor.vito_warmwasser_aufladung` | WW-Aufladung | splitter |
| `binary_sensor.vito_warmwasser_auslauftemperatur_sensorfehler` | Auslauftemperatur Sensorfehler | splitter |
| `binary_sensor.vito_warmwasser_ladepumpe` | WW-Pumpe | splitter |
| `binary_sensor.vito_warmwasser_speichertemperatur_sensorfehler` | Speichertemperatur Sensorfehler | splitter |
| `button.vito_warmwasser_boost` | Boost | extras |
| `button.vito_warmwasser_zeitprogramm_zuruecksetzen` | Zeitprogramm zurücksetzen | extras |
| `number.vito_warmwasser_boost_dauer` | Boost-Dauer | extras |
| `number.vito_warmwasser_solltemperatur` | WW-Temperatur | splitter |
| `sensor.vito_warmwasser_ladepumpe_laufzeit_heute` | Speicherladepumpe Laufzeit heute | extras |
| `sensor.vito_warmwasser_speichertemperatur` | WW-Speichertemperatur | splitter |
| `sensor.vito_warmwasser_zeitprogramm` | Zeitprogramm | extras |
| `switch.vito_warmwasser_dauerbetrieb` | Dauerbetrieb | extras |
| `water_heater.vito_warmwasser` | (device name) | splitter |

## Heizung Zirkulation

| Entity | Name | Source |
|---|---|---|
| `binary_sensor.vito_zirkulationspumpe` | WW-Zirkulationspumpe | splitter |
| `button.vito_zirkulation_boost` | Pumpe Boost | extras |
| `button.vito_zirkulation_zeitprogramm_zuruecksetzen` | Zeitprogramm zurücksetzen | extras |
| `number.vito_zirkulation_boost_dauer` | Pumpe Boost-Dauer | extras |
| `sensor.vito_zirkulation_zeitprogramm` | Zeitprogramm | extras |
| `sensor.vito_zirkulationspumpe_laufzeit_heute` | Pumpe Laufzeit heute | extras |
| `switch.vito_zirkulation_dauerbetrieb` | Pumpe Dauerbetrieb | extras |

## Heizung Solar

| Entity | Name | Source |
|---|---|---|
| `binary_sensor.vito_solar_kollektortemperatur_sensorfehler` | Kollektortemperatur Sensorfehler | splitter |
| `binary_sensor.vito_solar_nachladeunterdrueckung` | Nachladeunterdrückung | splitter |
| `binary_sensor.vito_solar_speichertemperatur_sensorfehler` | Speichertemperatur Sensorfehler | splitter |
| `binary_sensor.vito_solarpumpe` | Solarpumpe | splitter |
| `sensor.vito_solar_gesamtertrag` | Gesamtertrag | splitter |
| `sensor.vito_solar_kollektortemperatur` | Solarkollektor-Temperatur | splitter |
| `sensor.vito_solar_speichertemperatur` | Solarspeicher-Temperatur | splitter |
| `sensor.vito_solar_temperaturdifferenz_kollektor_speicher` | Temperaturdifferenz Kollektor/Speicher | extras |
| `sensor.vito_solarertrag_gestern` | Ertrag gestern | splitter |
| `sensor.vito_solarertrag_heute` | Ertrag heute | splitter |
| `sensor.vito_solarertrag_letzte_7_tage` | Ertrag letzte 7 Tage | splitter |
| `sensor.vito_solarpumpe_laufzeit_heute` | Kreispumpe Laufzeit heute | extras |

## Heizkreis 1 (Fußbodenheizung)

| Entity | Name | Source |
|---|---|---|
| `binary_sensor.vito_hk1_betriebsart_dauernd_normal` | Betriebsart Dauernd Normal | splitter |
| `binary_sensor.vito_hk1_betriebsart_dauernd_reduziert` | Betriebsart Dauernd Reduziert | splitter |
| `binary_sensor.vito_hk1_betriebsart_heizen_warmwasser` | Betriebsart Warmwasser und Heizung | splitter |
| `binary_sensor.vito_hk1_betriebsart_standby` | Betriebsart Standby | splitter |
| `binary_sensor.vito_hk1_betriebsart_warmwasser` | Betriebsart Warmwasser | splitter |
| `binary_sensor.vito_hk1_frostschutz` | Frostschutz | splitter |
| `binary_sensor.vito_hk1_partybetrieb` | Partybetrieb (Komfort) | splitter |
| `binary_sensor.vito_hk1_programm_normal` | Programm Normal | splitter |
| `binary_sensor.vito_hk1_programm_reduziert` | Programm Reduziert | splitter |
| `binary_sensor.vito_hk1_programm_standby` | Programm Standby | splitter |
| `binary_sensor.vito_hk1_pumpe` | Heizkreisumwälzpumpe | splitter |
| `binary_sensor.vito_hk1_sparbetrieb` | Sparbetrieb (Eco) | splitter |
| `binary_sensor.vito_hk1_vorlauftemperatur_sensorfehler` | Vorlauftemperatur Sensorfehler | splitter |
| `button.vito_hk1_boost` | Boost | extras |
| `button.vito_hk1_zeitprogramm_zuruecksetzen` | Zeitprogramm zurücksetzen | extras |
| `climate.vito_hk1_heizung` | (device name) | splitter |
| `number.vito_hk1_boost_dauer` | Boost-Dauer | extras |
| `number.vito_hk1_heizkurve_niveau` | Verschiebung der Heizkurve | splitter |
| `number.vito_hk1_heizkurve_steigung` | Steigung der Heizkurve | splitter |
| `number.vito_hk1_komforttemperatur` | Komforttemperatur | splitter |
| `number.vito_hk1_normaltemperatur` | Normaltemperatur | splitter |
| `number.vito_hk1_reduzierte_temperatur` | Reduzierte Temperatur | splitter |
| `select.vito_hk1_betriebsart` | Betriebsart | splitter |
| `sensor.vito_hk1_programm` | Programm | splitter |
| `sensor.vito_hk1_pumpe_laufzeit_heute` | Pumpe Laufzeit heute | extras |
| `sensor.vito_hk1_raumsolltemperatur_aktuell` | Raum-Solltemperatur aktuell | splitter |
| `sensor.vito_hk1_soll_vorlauftemperatur_heizkurve` | Soll-Vorlauftemperatur (Heizkurve) | extras |
| `sensor.vito_hk1_vorlauf_abweichung_zur_heizkurve` | Vorlauf Abweichung zur Heizkurve | extras |
| `sensor.vito_hk1_vorlaufsolltemperatur` | Vorlauf-Solltemperatur (Regler) | splitter |
| `sensor.vito_hk1_vorlauftemperatur` | Vorlauftemperatur | splitter |
| `sensor.vito_hk1_zeitprogramm` | Zeitprogramm | extras |
| `switch.vito_hk1_dauerbetrieb` | Dauerbetrieb | extras |
| `text.vito_hk1_name` | Name | extras |

## Heizkreis 2 (Heizkörper)

| Entity | Name | Source |
|---|---|---|
| `binary_sensor.vito_hk2_betriebsart_dauernd_normal` | Betriebsart Dauernd Normal | splitter |
| `binary_sensor.vito_hk2_betriebsart_dauernd_reduziert` | Betriebsart Dauernd Reduziert | splitter |
| `binary_sensor.vito_hk2_betriebsart_heizen_warmwasser` | Betriebsart Warmwasser und Heizung | splitter |
| `binary_sensor.vito_hk2_betriebsart_standby` | Betriebsart Standby | splitter |
| `binary_sensor.vito_hk2_betriebsart_warmwasser` | Betriebsart Warmwasser | splitter |
| `binary_sensor.vito_hk2_frostschutz` | Frostschutz | splitter |
| `binary_sensor.vito_hk2_partybetrieb` | Partybetrieb (Komfort) | splitter |
| `binary_sensor.vito_hk2_programm_normal` | Programm Normal | splitter |
| `binary_sensor.vito_hk2_programm_reduziert` | Programm Reduziert | splitter |
| `binary_sensor.vito_hk2_programm_standby` | Programm Standby | splitter |
| `binary_sensor.vito_hk2_pumpe` | Heizkreisumwälzpumpe | splitter |
| `binary_sensor.vito_hk2_sparbetrieb` | Sparbetrieb (Eco) | splitter |
| `binary_sensor.vito_hk2_vorlauftemperatur_sensorfehler` | Vorlauftemperatur Sensorfehler | splitter |
| `button.vito_hk2_boost` | Boost | extras |
| `button.vito_hk2_zeitprogramm_zuruecksetzen` | Zeitprogramm zurücksetzen | extras |
| `climate.vito_hk2_heizung` | (device name) | splitter |
| `number.vito_hk2_boost_dauer` | Boost-Dauer | extras |
| `number.vito_hk2_heizkurve_niveau` | Verschiebung der Heizkurve | splitter |
| `number.vito_hk2_heizkurve_steigung` | Steigung der Heizkurve | splitter |
| `number.vito_hk2_komforttemperatur` | Komforttemperatur | splitter |
| `number.vito_hk2_normaltemperatur` | Normaltemperatur | splitter |
| `number.vito_hk2_reduzierte_temperatur` | Reduzierte Temperatur | splitter |
| `select.vito_hk2_betriebsart` | Betriebsart | splitter |
| `sensor.vito_hk2_programm` | Programm | splitter |
| `sensor.vito_hk2_pumpe_laufzeit_heute` | Pumpe Laufzeit heute | extras |
| `sensor.vito_hk2_raumsolltemperatur_aktuell` | Raum-Solltemperatur aktuell | splitter |
| `sensor.vito_hk2_soll_vorlauftemperatur_heizkurve` | Soll-Vorlauftemperatur (Heizkurve) | extras |
| `sensor.vito_hk2_vorlauf_abweichung_zur_heizkurve` | Vorlauf Abweichung zur Heizkurve | extras |
| `sensor.vito_hk2_vorlaufsolltemperatur` | Vorlauf-Solltemperatur (Regler) | splitter |
| `sensor.vito_hk2_vorlauftemperatur` | Vorlauftemperatur | splitter |
| `sensor.vito_hk2_zeitprogramm` | Zeitprogramm | extras |
| `switch.vito_hk2_dauerbetrieb` | Dauerbetrieb | extras |
| `text.vito_hk2_name` | Name | extras |
