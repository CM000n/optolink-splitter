# Advanced Heating Control V5 with the Vitotronic

How the blueprint [Advanced Heating Control V5](https://github.com/panhans/HomeAssistant) (AHC) uses the entities of this integration and of
the radiator thermostats directly, without helpers.

## Blueprint extension

The AHC selectors only listed `input_number` for the temperatures and `input_boolean` / `binary_sensor` for the overrides, although the
blueprint only reads the states. A thermostat's comfort / eco temperature is a `sensor`, a heating controller's set points are `number`
and its comfort / eco operation `switch` entities. The extension (pull request
[panhans/HomeAssistant#180](https://github.com/panhans/HomeAssistant/pull/180), branch `feat/number-sensor-switch-inputs` of
`CM000n/HomeAssistant-1`):

* comfort / eco temperature (and their fallback entities) and the window open temperature entity accept `number` and temperature `sensor`
* force max, force eco, party, guest mode, presence sensor and winter mode accept `switch`
* new input `input_temperature_party` (party temperature entity). Order: number at the end of the party entity's name (the old way),
  then this entity, then the comfort temperature
* `float(none)` for the comfort / eco entity: an `unavailable` entity falls through to the fallback temperature instead of aborting the run
* write back (UI / physical change sync, adjustments) only into `input_number` / `number`, never into a `sensor`; the service is taken from
  the entity's domain

Until it is merged the automations use a local copy, `local/advanced_heating_control_entities.yaml` (5.5.9 plus the pull request, with a
different name and without `source_url`, so that blueprint updaters leave it alone). After a merge and an update of the upstream
blueprint, set `use_blueprint.path` of the automations back to `panhans/advanced_heating_control.yaml` and delete the local copy.

## Wiring

All automations use the time program of the controller through its schedule helper
(`schedule.vito_heizkreis_2_heizkorper_zeitprogramm`, synced by `extras/`).

| AHC input | Room thermostats (bathroom, office) | Heating circuit 2 itself (`climate.vito_hk2_heizung`, automation switched off) |
|---|---|---|
| Comfort Temperature | `sensor.comet_dect_<n>_komfort_temperatur` | `number.vito_hk2_normaltemperatur` |
| Eco Temperature | `sensor.comet_dect_<n>_eco_temperatur` | `number.vito_hk2_reduzierte_temperatur` |
| Party mode | none | `switch.vito_hk2_komfortbetrieb` |
| Party Temperature | none | `number.vito_hk2_komforttemperatur` |
| Force Eco Temperature | none | `switch.vito_hk2_sparbetrieb` |

* The room thermostats have their own settings (the comfort / eco temperature that is stored in the thermostat, set in the FRITZ!Box).
  They do not follow the set points of the Vitotronic. The static temperatures (22 / 18) stay as fallback.
* The automation of the heating circuit itself observes: its target equals what the controller already has (set point of the active
  phase), so it writes nothing as long as both agree. It is switched off because the controller runs the time program itself.

## Cautions

* The sync features of AHC (*UI change*, *physical change*, adjustments) write the changed temperature into the comfort / eco entity. With
  a `number` of the Vitotronic that would write the controller's EEPROM at every tweak of a thermostat. Keep them off for such automations.
* The comfort / eco switches cancel each other in the Vitotronic. AHC ranks party above force eco. When both change in the same moment
  (Komfortbetrieb -> Sparbetrieb) AHC may restore a scene saved at the start of the party and stop without evaluating the new situation;
  `input_party_legacy_restore: true` avoids that (every end of a party or open window is evaluated again). Observed once in tests; it is
  not needed for the room thermostats, which have no party or force eco entities.
* `change_temperature` of the blueprint renders `trigger.to_state.attributes.temperature | float`; when AHC switches a thermostat to
  `off` the attribute is `None` and the run of the trigger `temperature_change_valve_target` aborts (log noise, no function lost). A fix
  is open upstream as panhans/HomeAssistant#174, so it is not part of the pull request above.

## Tested

On the real controller, before the helpers were dropped: Sparbetrieb, Komfortbetrieb, Komfort -> Spar, Dauernd Tagbetrieb, Dauernd reduziert
and Aus each switched the rooms as expected. With the final wiring: the traces of both room automations show the values of the thermostat
sensors (`temperature_comfort_of_entity = 22.0`, `temperature_eco_of_entity = 18.0`); the circuit automation shows
`active_party_entity = switch.vito_hk2_komfortbetrieb` and `party_temp = 22.0` (from the `number`) while Komfortbetrieb is on.

An earlier variant mirrored the Vitotronic values into `input_number` helpers and template sensors and carried the party temperature in the
name of a sensor ("... Party 22"). The extension makes both unnecessary.
