# Advanced Heating Control V5 with the Vitotronic

How the radiator thermostats of single rooms (here: FRITZ!DECT Comet in bathroom and office, heating circuit 2 "Heizkörper")
follow the Vitotronic through the blueprint [Advanced Heating Control V5](https://github.com/panhans/HomeAssistant) (AHC).
The blueprint stays unchanged; a small Home Assistant package ([examples/heizplan_vito.yaml](examples/heizplan_vito.yaml)) adapts the
Vitotronic entities to what the blueprint accepts.

## Mapping

The Vitotronic is the source of truth, AHC only reads. The time program already comes from the schedule helper
(`schedule.vito_heizkreis_2_heizkorper_zeitprogramm`, synced with the controller by `extras/`), so the schedule input stays as it is.

| Vitotronic | AHC input | Adapter entity |
|---|---|---|
| Solltemperatur Normal | Comfort Temperature | `input_number.heizplan_hk2_normaltemperatur` (mirror) |
| Solltemperatur Reduziert | Eco Temperature | `input_number.heizplan_hk2_reduzierte_temperatur` (mirror) |
| Betrieb 2: Komfortbetrieb, Betriebsart Dauernd Tagbetrieb | Party mode | `binary_sensor.heizplan_hk2_party` |
| Betrieb 1: Sparbetrieb, Betriebsart Dauernd reduziert, Urlaubsprogramm | Force Eco Temperature | `binary_sensor.heizplan_hk2_eco_erzwungen` |
| Betriebsart Aus / Nur Warmwasser aktiv (and the heating period) | Winter Mode / Automation Toggle | `binary_sensor.heizplan_hk2_heizen_freigegeben` |
| Solltemperatur Komfort | temperature of the party | number at the end of the party sensor's name ("Heizplan HK2 Party 22") |

AHC inputs of a room automation (the static temperatures stay as fallback):

```yaml
input_temperature_comfort: input_number.heizplan_hk2_normaltemperatur
input_temperature_eco: input_number.heizplan_hk2_reduzierte_temperatur
input_mode_party: [binary_sensor.heizplan_hk2_party]
input_force_eco_temperature: binary_sensor.heizplan_hk2_eco_erzwungen
input_mode_winter: binary_sensor.heizplan_hk2_heizen_freigegeben
input_party_legacy_restore: true
```

## Why an adapter instead of a patched blueprint

* The AHC selectors for the temperatures only list `input_number`, for party / force eco only `input_boolean`, `binary_sensor`, `timer`.
  They are UI filters; at run time AHC only reads the states, so the filters are the only obstacle.
* A mirror `input_number` decouples the rooms from the controller. AHC computes `states(entity) | float` without a default; if the
  Pi or MQTT is down the `number` entities are `unavailable` and the run aborts. An `input_number` keeps its last value.
* AHC can write back into the comfort / eco entity (UI / physical sync, adjustments). Pointed at the Vitotronic numbers that would
  write the controller's EEPROM at every tweak of a thermostat. Pointed at the mirror it is harmless. Keep both syncs off anyway.
* The blueprint can still be updated.

The mirror is one way (automation `heizplan_vito_temperaturen_spiegeln`): a manual edit of the mirror is reverted at once.

## Behaviour (tested on the real controller)

| Action | Rooms |
|---|---|
| Sparbetrieb on | eco temperature, `off` if the room is already warmer (AHC "off if above room temperature") |
| Sparbetrieb off | back to the schedule |
| Komfortbetrieb on | party, comfort temperature |
| Komfortbetrieb -> Sparbetrieb | eco |
| Dauernd Tagbetrieb | party with the normal temperature |
| Dauernd reduziert | eco |
| Aus / Nur Warmwasser aktiv | `off` |

`input_party_legacy_restore` is on because party and force eco often change in the same moment (Komfortbetrieb -> Sparbetrieb,
Dauernd Tagbetrieb -> Dauernd reduziert). AHC then restores a scene saved at the start of the party and stops, without evaluating
the new situation; depending on the order of the two runs the rooms stayed on the old target. With the legacy restore every end of
a party (and of an open window) is evaluated again.

## Findings about the blueprint (5.5.7 installed, 5.5.9 upstream)

* `change_temperature` renders `trigger.to_state.attributes.temperature | float`. When AHC switches a thermostat to `off` the
  attribute is `None`, the run of the trigger `temperature_change_valve_target` aborts with "float got invalid input 'None'"
  (log noise, no function lost). `float(none)` would fix it.
* `states(comfort entity) | float`, `states(eco entity) | float` and the window open temperature entity have no default either.
* After a scene restore (party / window end) AHC stops without evaluating, see above.
* The selectors are domain locked (`input_number`, `input_boolean`, ...), although `number` / `switch` would work at run time.
