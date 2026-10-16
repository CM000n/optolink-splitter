"""
Optolink-Splitter / Home Assistant datapoint + entity definition for a
Viessmann Vitotronic 200, device ident 0x20CB ("VScotHO1", VS2/P300) with
two heating circuits, DHW cylinder, DHW circulation pump and solar thermal.

Circuit mapping (verified against the ViCare cloud API of this installation):
  HK1 (Fussbodenheizung)  = Vitotronic circuit M2, address base 0x3000
  HK2 (Heizkoerper)       = Vitotronic circuit M3, address base 0x4000
  M1 / A1M1 (base 0x2000) is unused here (factory defaults).
Per-circuit offsets (relative to the base):
  0x0301 active program   0x0306 normal / 0x0307 reduced / 0x0308 comfort set point (1 byte, deg C)
  0x0309/0x0311 holiday start / end (8 byte BCD, 1970-01-01 = unset)
  0x0302 eco ("Spar") / 0x0303 party flag      0x0323 operating mode (0..4)
  0x0500 status block (set point of the active program = bytes 12-13)   0x0544 flow set point
  0x0549 frost protection 0x07D3 heating curve slope (x0.1) 0x07D4 level  0x0900 flow temperature
  0x0904 flow sensor status 0x0906 pump   0x0000 time program (7 days x 8 byte, read as 48 + 8 byte)

The entities are grouped into sub-devices (Anlage, Kessel, Warmwasser, Zirkulation, Solar, Heizkreis 1/2)
via the 'devices' / 'entity_meta' tables, see homeassistant_publish.py.
Writable entities use the '<topic>/<datapoint>/set' topics of the splitter (see wiki "MQTT set Topics").
"""

# --------------------------------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------------------------------
MAIN = "Vitotronic_VScotHO1"
HK_BASE = {1: 0x3000, 2: 0x4000}
HK_DEVICE = {1: "heizkreis_1", 2: "heizkreis_2"}

DOMAIN_ORDER = ["sensor", "binary_sensor", "number", "select", "climate", "water_heater", "button"]
_poll = {d: [] for d in DOMAIN_ORDER}
_nopoll = {d: [] for d in DOMAIN_ORDER}
_meta = {}

TEMP = {
    "unit_of_measurement": "°C",
    "device_class": "temperature",
    "state_class": "measurement",
    "suggested_display_precision": 1,
}


def poll(domain, dp, item, **meta):
    """Polled datapoint 'dp'; item = (cycle, addr, length[, 'b:..'][, scale/type[, signed]])."""
    _poll[domain].append((item[0], dp) + tuple(item[1:]))
    _meta[dp] = meta


def derived(domain, dp, state_from=None, value_template=None, **meta):
    """Entity without its own datapoint (HA-side view of another topic)."""
    entry = {"name": dp}
    if state_from:
        entry["state_topic"] = "{mqtt_base}/" + state_from
    if value_template:
        entry["value_template"] = value_template
    _nopoll[domain].append(entry)
    _meta[dp] = meta


def hidden(dp, item, **meta):
    """Polled raw datapoint that only other tools (vito_extras.py) consume: published on MQTT, no HA entity."""
    poll("sensor", dp, item, discovery=False, **meta)


def set_topic(dp):
    return "{mqtt_base}/" + dp + "/set"


# --------------------------------------------------------------------------------------------------------------
# value templates
# --------------------------------------------------------------------------------------------------------------
MODE_OPTIONS = [
    "Aus",
    "Nur Warmwasser aktiv",
    "Heizung & Warmwasser aktiv",
    "Dauernd reduziert",
    "Dauernd Tagbetrieb",
]  # as in the ViCare app
MODE_TO_TEXT = (
    "{% set m = {'0':'Aus','1':'Nur Warmwasser aktiv','2':'Heizung & Warmwasser aktiv',"
    "'3':'Dauernd reduziert','4':'Dauernd Tagbetrieb'} %}"
    "{{ m.get(value | string | trim, 'Unbekannt (' ~ value ~ ')') }}"
)
TEXT_TO_MODE = (
    "{% set m = {'Aus':0,'Nur Warmwasser aktiv':1,'Heizung & Warmwasser aktiv':2,"
    "'Dauernd reduziert':3,'Dauernd Tagbetrieb':4} %}{{ m[value] }}"
)
HVAC_FROM_MODE = (
    "{% set m = {'0':'off','1':'off','2':'auto','3':'off','4':'heat'} %}{{ m.get(value | string | trim, 'off') }}"
)
HVAC_TO_MODE = "{% set m = {'off':3,'auto':2,'heat':4} %}{{ m[value] }}"
ACTION_FROM_MODULATION = "{{ 'heating' if value | float(0) > 0 else 'idle' }}"
# 7 days x 4 byte (little endian Wh) -> kWh, first 7 daily values of the 28 byte block at 0xCF30 (today .. 6 days ago)
SOLAR_7D = (
    "{% set ns = namespace(t=0) %}{% for i in range(7) %}{% set c = value[i*8:i*8+8] %}"
    "{% set ns.t = ns.t + ((c[6:8] ~ c[4:6] ~ c[2:4] ~ c[0:2]) | int(0, 16)) %}{% endfor %}"
    "{{ (ns.t / 1000) | round(3) }}"
)
TIME_DRIFT = (
    "{% set t = strptime(value[3:], '%d.%m.%Y %H:%M:%S').replace(tzinfo=now().tzinfo) %}"
    "{{ 'true' if (t is not none and ((now() - t).total_seconds() | abs < 400)) else 'false' }}"
)

# --------------------------------------------------------------------------------------------------------------
# Anlage
# --------------------------------------------------------------------------------------------------------------
A = {"device": "anlage"}
poll("sensor", "aussentemperatur", ("OFTEN", 0x0800, 2, 0.1, True), name="Außentemperatur", **A, **TEMP)
for dp, addr, label, note in (
    ("aussentemperatur_gedaempft", 0x5523, "Außentemperatur gedämpft", "slow damping, used for the building"),
    ("aussentemperatur_gefiltert", 0x5525, "Außentemperatur gefiltert", "short low pass"),
    (
        "aussentemperatur_gemischt",
        0x5527,
        "Außentemperatur gemischt (Regelung)",
        "mix of both: the value the heating curve works with",
    ),
):
    poll(
        "sensor",
        dp,
        ("OFTEN", addr, 2, 0.1, True),
        name=label,
        icon="mdi:thermometer-lines",
        entity_category="diagnostic",
        **A,
        **TEMP,
    )
poll(
    "binary_sensor",
    "aussentemperatur_sensorfehler",
    ("SOMETIMES", 0x083A, 1, "onoff"),
    name="Außentemperatur Sensorfehler",
    icon="mdi:thermometer-alert",
    device_class="problem",
    entity_category="diagnostic",
    **A,
)
poll(
    "sensor",
    "regler_seriennummer",
    ("ONCEONLY", 0xF000, 16, "utf8"),
    name="Regler Seriennummer",
    icon="mdi:barcode",
    entity_category="diagnostic",
    **A,
)
poll(
    "binary_sensor",
    "sammelstoerung",
    ("SOMETIMES", 0x0A82, 1, "onoff"),
    name="Sammelstörung",
    device_class="problem",
    icon="mdi:alert-circle-outline",
    **A,
)
poll(
    "binary_sensor",
    "anlagenzeit_abweichung",
    ("SOMETIMES", 0x088E, 8, "vdatetime"),
    name="Anlagenzeit weicht ab",
    device_class="problem",
    entity_category="diagnostic",
    icon="mdi:clock-alert-outline",
    payload_on="false",
    payload_off="true",
    value_template=TIME_DRIFT,
    **A,
)
# holiday program dates of the first circuit (the ViCare app writes all three circuits alike); the date entities
# "Urlaubsprogramm Beginn / Ende" of extras/vito_extras.py show and set them
hidden(
    "urlaubsprogramm_beginn",
    ("SOMETIMES", 0x3309, 16, "b:0:7", "vdatetime"),
    name="Urlaubsprogramm Beginn (Rohwert)",
    **A,
)
hidden(
    "urlaubsprogramm_ende", ("SOMETIMES", 0x3309, 16, "b:8:15", "vdatetime"), name="Urlaubsprogramm Ende (Rohwert)", **A
)

# --------------------------------------------------------------------------------------------------------------
# Kessel
# --------------------------------------------------------------------------------------------------------------
K = {"device": "kessel"}
poll("sensor", "kesseltemperatur", ("OFTEN", 0x0802, 2, 0.1, True), name="Kesseltemperatur", **K, **TEMP)
poll(
    "sensor",
    "kesselsolltemperatur",
    ("OFTEN", 0x555A, 2, 0.1, True),
    name="Solltemperatur",
    icon="mdi:thermometer-water",
    **K,
    **TEMP,
)
poll(
    "sensor", "abgastemperatur", ("OFTEN", 0x0808, 2, 0.1, True), name="Abgastemperatur", icon="mdi:smoke", **K, **TEMP
)
poll(
    "sensor",
    "brennermodulation",
    ("ALWAYS", 0x55D3, 1, 1),
    name="Brennermodulation",
    icon="mdi:percent",
    unit_of_measurement="%",
    state_class="measurement",
    suggested_display_precision=0,
    **K,
)
poll(
    "sensor",
    "brennerstarts",
    ("OFTEN", 0x088A, 4, 1),
    name="Brennerstarts",
    icon="mdi:counter",
    state_class="total_increasing",
    suggested_display_precision=0,
    entity_category="diagnostic",
    **K,
)
poll(
    "sensor",
    "brennerlaufzeit",
    ("SOMETIMES", 0x08A7, 4, 2.7777778e-4),
    name="Brennerbetriebsstunden",
    icon="mdi:counter",
    unit_of_measurement="h",
    device_class="duration",
    state_class="total_increasing",
    suggested_display_precision=1,
    entity_category="diagnostic",
    **K,
)
derived(
    "binary_sensor",
    "brenner_aktiv",
    "brennermodulation",
    "{{ 'ON' if value | float(0) > 0 else 'OFF' }}",
    name="Brenner",
    icon="mdi:gas-burner",
    device_class="running",
    **K,
)
poll(
    "binary_sensor",
    "interne_kesselpumpe",
    ("OFTEN", 0x7660, 1, "onoff"),
    name="Interne Kesselpumpe",
    icon="mdi:pump",
    device_class="running",
    **K,
)
poll(
    "binary_sensor",
    "kesseltemperatur_sensorfehler",
    ("SOMETIMES", 0x083B, 1, "onoff"),
    name="Temperatur Sensorfehler",
    icon="mdi:thermometer-alert",
    device_class="problem",
    entity_category="diagnostic",
    **K,
)

# --------------------------------------------------------------------------------------------------------------
# Warmwasser / Zirkulation
# --------------------------------------------------------------------------------------------------------------
W = {"device": "warmwasser"}
poll(
    "sensor",
    "warmwasser_speichertemperatur",
    ("OFTEN", 0x0804, 2, 0.1, True),
    name="WW-Speichertemperatur",
    **W,
    **TEMP,
)
poll(
    "number",
    "warmwasser_solltemperatur",
    ("SOMETIMES", 0x6300, 1, 1),
    name="WW-Temperatur",
    command_topic=set_topic("warmwasser_solltemperatur"),
    min=10,
    max=60,
    step=1,
    mode="box",
    unit_of_measurement="°C",
    device_class="temperature",
    icon="mdi:water-thermometer",
    **W,
)
poll(
    "binary_sensor",
    "warmwasser_ladepumpe",
    ("OFTEN", 0x6513, 1, "onoff"),
    name="WW-Pumpe",
    icon="mdi:pump",
    device_class="running",
    **W,
)
derived(
    "binary_sensor",
    "warmwasser_aufladung",
    "warmwasser_ladepumpe",
    name="WW-Aufladung",
    icon="mdi:water-boiler",
    device_class="running",
    **W,
)
poll(
    "binary_sensor",
    "warmwasser_speichertemperatur_sensorfehler",
    ("SOMETIMES", 0x083C, 1, "onoff"),
    name="Speichertemperatur Sensorfehler",
    icon="mdi:thermometer-alert",
    device_class="problem",
    entity_category="diagnostic",
    **W,
)
poll(
    "binary_sensor",
    "warmwasser_auslauftemperatur_sensorfehler",
    ("SOMETIMES", 0x083F, 1, "onoff"),
    name="Auslauftemperatur Sensorfehler",
    icon="mdi:thermometer-alert",
    device_class="problem",
    entity_category="diagnostic",
    **W,
)
derived(
    "water_heater",
    "warmwasser",
    name=None,
    icon="mdi:water-boiler",
    current_temperature_topic="{mqtt_base}/warmwasser_speichertemperatur",
    temperature_state_topic="{mqtt_base}/warmwasser_solltemperatur",
    temperature_command_topic=set_topic("warmwasser_solltemperatur"),
    temperature_unit="C",
    min_temp=10,
    max_temp=60,
    precision=1.0,
    **W,
)

Z = {"device": "zirkulation"}
poll(
    "binary_sensor",
    "zirkulationspumpe",
    ("OFTEN", 0x6515, 1, "onoff"),
    name="WW-Zirkulationspumpe",
    icon="mdi:pump",
    device_class="running",
    **Z,
)

# --------------------------------------------------------------------------------------------------------------
# Solar
# --------------------------------------------------------------------------------------------------------------
S = {"device": "solar"}
poll(
    "sensor",
    "solar_kollektortemperatur",
    ("OFTEN", 0x6564, 2, 0.1, True),
    name="Solarkollektor-Temperatur",
    **S,
    **TEMP,
)
poll(
    "sensor", "solar_speichertemperatur", ("OFTEN", 0x6566, 2, 0.1, True), name="Solarspeicher-Temperatur", **S, **TEMP
)
poll(
    "binary_sensor",
    "solarpumpe",
    ("OFTEN", 0x6552, 1, "onoff"),
    name="Solarpumpe",
    icon="mdi:pump",
    device_class="running",
    **S,
)
poll(
    "binary_sensor",
    "solar_nachladeunterdrueckung",
    ("SOMETIMES", 0x6551, 2, "b:0:0", "onoff"),
    name="Nachladeunterdrückung",
    icon="mdi:battery-off-outline",
    **S,
)
poll(
    "binary_sensor",
    "solar_kollektortemperatur_sensorfehler",
    ("SOMETIMES", 0x5723, 1, "onoff"),
    name="Kollektortemperatur Sensorfehler",
    icon="mdi:thermometer-alert",
    device_class="problem",
    entity_category="diagnostic",
    **S,
)
poll(
    "binary_sensor",
    "solar_speichertemperatur_sensorfehler",
    ("SOMETIMES", 0x5724, 1, "onoff"),
    name="Speichertemperatur Sensorfehler",
    icon="mdi:thermometer-alert",
    device_class="problem",
    entity_category="diagnostic",
    **S,
)
poll(
    "sensor",
    "solar_gesamtertrag",
    ("SOMETIMES", 0x6560, 4, 1),
    name="Gesamtertrag",
    icon="mdi:solar-power-variant",
    unit_of_measurement="kWh",
    device_class="energy",
    state_class="total_increasing",
    suggested_display_precision=0,
    **S,
)
poll(
    "sensor",
    "solarertrag_heute",
    ("SOMETIMES", 0xCF30, 4, 0.001),
    name="Ertrag heute",
    icon="mdi:solar-power-variant",
    unit_of_measurement="kWh",
    device_class="energy",
    state_class="total_increasing",
    suggested_display_precision=1,
    **S,
)
poll(
    "sensor",
    "solarertrag_gestern",
    ("SOMETIMES", 0xCF30, 8, "b:4:7", 0.001),
    name="Ertrag gestern",
    icon="mdi:solar-power-variant",
    unit_of_measurement="kWh",
    device_class="energy",
    state_class="measurement",
    suggested_display_precision=1,
    **S,
)  # 0xCF34 itself is rejected as start address
hidden("solarertrag_tageswerte_roh", ("SOMETIMES", 0xCF30, 28, "raw"), name="Solarertrag Tageswerte (Rohdaten)", **S)
derived(
    "sensor",
    "solarertrag_letzte_7_tage",
    "solarertrag_tageswerte_roh",
    SOLAR_7D,
    name="Ertrag letzte 7 Tage",
    icon="mdi:solar-power-variant",
    unit_of_measurement="kWh",
    device_class="energy",
    state_class="measurement",
    suggested_display_precision=1,
    **S,
)

# --------------------------------------------------------------------------------------------------------------
# Heizkreise (HK1 = M2, HK2 = M3)
# --------------------------------------------------------------------------------------------------------------
for n, B in HK_BASE.items():
    H = {"device": HK_DEVICE[n]}
    p = f"hk{n}_"
    poll("sensor", p + "vorlauftemperatur", ("OFTEN", B + 0x900, 2, 0.1, True), name="Vorlauftemperatur", **H, **TEMP)
    poll(
        "sensor",
        p + "vorlaufsolltemperatur",
        ("OFTEN", B + 0x544, 2, 0.1, True),
        name="Vorlauf-Solltemperatur (Regler)",
        icon="mdi:thermometer-check",
        **H,
        **TEMP,
    )
    poll(
        "sensor",
        p + "raumsolltemperatur_aktuell",
        ("OFTEN", B + 0x500, 22, "b:12:13", 0.1, False),
        name="Raum-Solltemperatur aktuell",
        icon="mdi:home-thermometer-outline",
        **H,
        **TEMP,
    )
    # phase of the circuit = byte 1 of the status block (0 off, 1 reduced, 2 normal, 3 permanently normal). It follows the
    # time program, unlike register 0x301, which only holds the selected operating program (1 = permanently reduced,
    # 2 = permanently normal, 3 = time program). Comfort is not a phase: it shows as the party flag (0x303) and the
    # comfort set point. Read together with the set point above (same block). Hidden: the entity "Aktiver Heizmodus"
    # (text like the ViCare app) is built from this, the operating mode and the time program by extras/vito_extras.py.
    hidden(p + "programm", ("OFTEN", B + 0x500, 22, "b:1:1", 1), name="Programm (Phase, Rohwert)", **H)
    hidden(p + "betriebsprogramm_roh", ("OFTEN", B + 0x301, 1, 1), name="Betriebsprogramm (Rohwert)", **H)
    poll(
        "binary_sensor",
        p + "pumpe",
        ("OFTEN", B + 0x906, 1, "onoff"),
        name="Heizkreisumwälzpumpe",
        icon="mdi:pump",
        device_class="running",
        **H,
    )
    poll(
        "binary_sensor",
        p + "frostschutz",
        ("OFTEN", B + 0x549, 1, "onoff"),
        name="Frostschutz",
        icon="mdi:snowflake",
        **H,
    )
    poll(
        "binary_sensor",
        p + "vorlauftemperatur_sensorfehler",
        ("SOMETIMES", B + 0x904, 1, "onoff"),
        name="Vorlauftemperatur Sensorfehler",
        icon="mdi:thermometer-alert",
        device_class="problem",
        entity_category="diagnostic",
        **H,
    )
    # comfort / eco status flags (set by the controller); the switches "Komfortbetrieb" / "Sparbetrieb" of
    # extras/vito_extras.py show them and write the command registers 0x330 / 0x331
    hidden(p + "partybetrieb", ("OFTEN", B + 0x303, 1, "onoff"), name="Komfortbetrieb (Status)", **H)
    hidden(p + "sparbetrieb", ("OFTEN", B + 0x302, 1, "onoff"), name="Sparbetrieb (Status)", **H)

    # operating mode: select (writes via /set)
    poll(
        "select",
        p + "betriebsart",
        ("OFTEN", B + 0x323, 1, 1),
        name="Betriebsart",
        icon="mdi:cog-transfer-outline",
        options=MODE_OPTIONS,
        value_template=MODE_TO_TEXT,
        command_template=TEXT_TO_MODE,
        command_topic=set_topic(p + "betriebsart"),
        optimistic=False,
        **H,
    )
    # set points and heating curve (writable numbers)
    for key, off, label in (
        ("normaltemperatur", 0x306, "Normaltemperatur"),
        ("reduzierte_temperatur", 0x307, "Reduzierte Temperatur"),
        ("komforttemperatur", 0x308, "Komforttemperatur"),
    ):
        poll(
            "number",
            p + key,
            ("SOMETIMES", B + off, 1, 1),
            name=label,
            command_topic=set_topic(p + key),
            min=3,
            max=37,
            step=1,
            mode="box",
            unit_of_measurement="°C",
            device_class="temperature",
            **H,
        )
    poll(
        "number",
        p + "heizkurve_steigung",
        ("SOMETIMES", B + 0x7D3, 1, 0.1),
        name="Steigung der Heizkurve",
        icon="mdi:slope-uphill",
        command_topic=set_topic(p + "heizkurve_steigung"),
        min=0.2,
        max=3.5,
        step=0.1,
        mode="box",
        **H,
    )
    poll(
        "number",
        p + "heizkurve_niveau",
        ("SOMETIMES", B + 0x7D4, 1, 1, True),
        name="Verschiebung der Heizkurve",
        icon="mdi:plus-minus-variant",
        command_topic=set_topic(p + "heizkurve_niveau"),
        min=-13,
        max=40,
        step=1,
        mode="box",
        unit_of_measurement="K",
        **H,
    )

    # time program (raw, consumed by vito_extras.py)
    hidden(p + "zeitprogramm_roh_1", ("SOMETIMES", B + 0x000, 48, "raw"), name="Zeitprogramm (Rohdaten 1)", **H)
    hidden(p + "zeitprogramm_roh_2", ("SOMETIMES", B + 0x030, 8, "raw"), name="Zeitprogramm (Rohdaten 2)", **H)

    # climate entity (mode via /set, set point + preset through vito_extras.py)
    derived(
        "climate",
        p + "heizung",
        name=None,
        icon="mdi:radiator",
        modes=["off", "auto", "heat"],
        mode_state_topic="{mqtt_base}/" + p + "betriebsart",
        mode_state_template=HVAC_FROM_MODE,
        mode_command_topic=set_topic(p + "betriebsart"),
        mode_command_template=HVAC_TO_MODE,
        current_temperature_topic="{mqtt_base}/" + p + "vorlauftemperatur",
        temperature_state_topic="{mqtt_base}/" + p + "raumsolltemperatur_aktuell",
        temperature_command_topic="VitoExt/" + p + "temperatur/set",
        preset_modes=["comfort", "eco", "home", "sleep"],
        preset_mode_state_topic="VitoExt/" + p + "preset",
        preset_mode_command_topic="VitoExt/" + p + "preset/set",
        action_topic="{mqtt_base}/brennermodulation",
        action_template=ACTION_FROM_MODULATION,
        temperature_unit="C",
        min_temp=3,
        max_temp=37,
        temp_step=1,
        precision=0.1,
        **H,
    )

# --------------------------------------------------------------------------------------------------------------
# time programs of DHW and circulation (raw, consumed by vito_extras.py)
# --------------------------------------------------------------------------------------------------------------
hidden("warmwasser_zeitprogramm_roh_1", ("SOMETIMES", 0x2100, 48, "raw"), name="Zeitprogramm (Rohdaten 1)", **W)
hidden("warmwasser_zeitprogramm_roh_2", ("SOMETIMES", 0x2130, 8, "raw"), name="Zeitprogramm (Rohdaten 2)", **W)
hidden("zirkulation_zeitprogramm_roh_1", ("SOMETIMES", 0x2200, 48, "raw"), name="Zeitprogramm (Rohdaten 1)", **Z)
hidden("zirkulation_zeitprogramm_roh_2", ("SOMETIMES", 0x2230, 8, "raw"), name="Zeitprogramm (Rohdaten 2)", **Z)

# --------------------------------------------------------------------------------------------------------------
# main device: force a full poll
# --------------------------------------------------------------------------------------------------------------
derived(
    "button",
    "forcepoll",
    name="Alle Werte neu lesen",
    icon="mdi:refresh",
    entity_category="diagnostic",
    command_topic="{mqtt_base}/cmnd",
    payload_press="forcepoll",
)

# --------------------------------------------------------------------------------------------------------------
# presentation: device, name and category of entities in Home Assistant (one table, so that the clustering is easy to review).
# Home Assistant sorts the entities of a device by category (controls, sensors, configuration, diagnostic) and then by name.
# --------------------------------------------------------------------------------------------------------------
PRESENTATION = {
    # burner: own device, short names (the device name says "Brenner")
    "brennermodulation": dict(device="brenner", name="Modulation"),
    "brennerstarts": dict(device="brenner", name="Starts gesamt"),
    "brennerlaufzeit": dict(device="brenner", name="Betriebsstunden"),
    "brenner_aktiv": dict(device="brenner", name="Aktiv"),
    # DHW
    "warmwasser_speichertemperatur": dict(name="Speichertemperatur"),
    "warmwasser_solltemperatur": dict(name="Solltemperatur"),
    "warmwasser_ladepumpe": dict(name="Ladepumpe"),
    "warmwasser_aufladung": dict(name="Aufladung"),
}
for _n in (1, 2):
    for _dp, _meta_update in {
        "normaltemperatur": dict(name="Solltemperatur Normal"),
        "reduzierte_temperatur": dict(name="Solltemperatur Reduziert"),
        "komforttemperatur": dict(name="Solltemperatur Komfort"),
        "heizkurve_steigung": dict(name="Heizkurve Steigung", entity_category="config"),
        "heizkurve_niveau": dict(name="Heizkurve Verschiebung", entity_category="config"),
        "vorlaufsolltemperatur": dict(name="Vorlauf Soll (Regler)", entity_category="diagnostic"),
        "pumpe": dict(name="Umwälzpumpe"),
    }.items():
        PRESENTATION[f"hk{_n}_{_dp}"] = _meta_update
for _dp, _meta_update in PRESENTATION.items():
    _meta[_dp].update(_meta_update)

# --------------------------------------------------------------------------------------------------------------
# the poll list
# --------------------------------------------------------------------------------------------------------------
# fmt: off
POLL_GROUPS = {
    "ONCEONLY":  0,   # once on start-up and on forcepoll
    "ALWAYS":    1,   #   5 s
    "OFTEN":     6,   #  30 s
    "SOMETIMES": 60,  #   5 min
    "RARELY":    720, #   1 h
    "DEBUG":     -1,  # never
}
# fmt: on

poll_list = {
    "device": {
        "identifiers": [MAIN],
        "name": "Viessmann Heizung",
        "model": "Vitotronic 200 (VScotHO1)",
        "manufacturer": "Viessmann",
    },
    "devices": {
        "anlage": {
            "identifiers": [MAIN + "_anlage"],
            "name": "Heizung Anlage",
            "model": "Anlage",
            "manufacturer": "Viessmann",
        },
        "kessel": {
            "identifiers": [MAIN + "_kessel"],
            "name": "Heizung Kessel",
            "model": "Kessel",
            "manufacturer": "Viessmann",
        },
        "brenner": {
            "identifiers": [MAIN + "_brenner"],
            "name": "Heizung Brenner",
            "model": "Brenner",
            "manufacturer": "Viessmann",
        },
        "warmwasser": {
            "identifiers": [MAIN + "_warmwasser"],
            "name": "Heizung Warmwasser",
            "model": "Warmwasser",
            "manufacturer": "Viessmann",
        },
        "zirkulation": {
            "identifiers": [MAIN + "_zirkulation"],
            "name": "Heizung Zirkulation",
            "model": "Zirkulation",
            "manufacturer": "Viessmann",
        },
        "solar": {
            "identifiers": [MAIN + "_solar"],
            "name": "Heizung Solar",
            "model": "Solar",
            "manufacturer": "Viessmann",
        },
        "heizkreis_1": {
            "identifiers": [MAIN + "_heizkreis_1"],
            "name": "Heizkreis 1 (Fußbodenheizung)",
            "model": "Heizkreis 1 (Fußbodenheizung)",
            "manufacturer": "Viessmann",
        },
        "heizkreis_2": {
            "identifiers": [MAIN + "_heizkreis_2"],
            "name": "Heizkreis 2 (Heizkörper)",
            "model": "Heizkreis 2 (Heizkörper)",
            "manufacturer": "Viessmann",
        },
    },
    "entity_meta": _meta,
    "node_id": "vitotronic",
    "dp_prefix": "vito_",
    "beautifier": {"search": [], "replace": [], "fixed": []},
    "poll_interval": 5,  # base polling interval [seconds]
    "poll_groups": POLL_GROUPS,
    "mqtt_delay": 0.1,
    "domains": [{"domain": d, "poll": _poll[d], "nopoll": _nopoll[d]} for d in DOMAIN_ORDER if _poll[d] or _nopoll[d]],
}
