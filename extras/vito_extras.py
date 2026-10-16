#!/usr/bin/env python3
'''
   vito_extras.py - derived entities and extra controls for the Optolink-Splitter (Vitotronic 200 VScotHO1)

   Companion service of optolinkvs2_switch.py. It never touches the serial port: it listens to the topics the
   splitter publishes (<topic>/<datapoint>), sends read/write commands to <topic>/cmnd and publishes its own entities
   below <ext_topic> with Home Assistant MQTT discovery (node id '<node_id>_extras'), grouped into the same
   sub-devices as the splitter's entities.

   Provides
   * burner statistics (starts last hour / today, run time today, last run / pause, average run time, cycling)
   * run time today of the pumps, heating curve target and deviation, solar temperature difference
   * time program state of the heating circuits, DHW and circulation, active heating mode (as in the ViCare app), climate preset
   * holiday program state and "end holiday"
   * climate set point and preset commands (writes the register of the active program, party / eco flags)
   * boost and permanent operation of the four time programs (rewrites the time program, original is saved and
     restored; this is how the ViCare integration did it through the cloud)
   * optional two-way sync of the four time programs with Home Assistant schedule helpers (needs extras_config.json
     and a long-lived access token, see docs/vscotho1.md)

   Safety: writes are restricted to a whitelist of registers (set points, party / eco flags, time program days,
   holiday dates), the original time programs are stored in the state file before anything is changed and
   every time program write is read back.

   Run from the repository root:  PYTHONPATH=. python extras/vito_extras.py
'''

import json
import logging
import os
import queue
import signal
import sys
import threading
import time
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for path in (ROOT, HERE):
    if path not in sys.path:
        sys.path.insert(0, path)

import paho.mqtt.client as paho  # noqa: E402

import vito_logic as logic  # noqa: E402
from ha_client import HaClient, HaError  # noqa: E402
from c_settings_adapter import settings  # noqa: E402
import homeassistant_poll_list as plist  # noqa: E402

log = logging.getLogger("vito_extras")

BASE = settings.mqtt_topic                      # topic of the splitter, e.g. "Vito"
EXT = BASE + "Ext"                              # topic of this service, e.g. "VitoExt"
POLL = plist.poll_list
PREFIX = POLL.get("dp_prefix", "vito_")
NODE = POLL.get("node_id", "vitotronic") + "_extras"
HA_PREFIX = POLL.get("discovery_prefix") or "homeassistant"
DEVICES = POLL["devices"]
MAIN_ID = POLL["device"]["identifiers"][0]
STATE_FILE = os.path.join(ROOT, "extras_state.json")
CONFIG_FILE = os.path.join(ROOT, "extras_config.json")       # optional, enables the schedule sync (see docs/vscotho1.md)
SYNC_INTERVAL = 20                                           # min. seconds between two schedule sync cycles (the ticker runs every 15 s, so ~30 s)
SCHEDULE_HELPERS = {                                         # time program -> (name of the HA schedule helper, icon)
    "hk1": ("Vito Heizkreis 1 (Fußbodenheizung) Zeitprogramm", "mdi:radiator"),
    "hk2": ("Vito Heizkreis 2 (Heizkörper) Zeitprogramm", "mdi:radiator"),
    "warmwasser": ("Vito Warmwasser Zeitprogramm", "mdi:water-boiler"),
    "zirkulation": ("Vito Zirkulation Zeitprogramm", "mdi:water-sync"),
}

# time programs: key -> (base address, device key, label)
OBSOLETE_DISCOVERY = tuple((domain, f"{hk}_{name}") for hk in ("hk1", "hk2") for domain, name in (
    ("button", "boost"), ("number", "boost_dauer"), ("switch", "dauerbetrieb"), ("button", "zeitprogramm_zuruecksetzen")))
SWITCH_HOLD = 20.0                                           # seconds a command is shown before polled flags may override it
SCHEDULES = {
    "hk1": (0x3000, "heizkreis_1", "Heizkreis 1"),
    "hk2": (0x4000, "heizkreis_2", "Heizkreis 2"),
    "warmwasser": (0x2100, "warmwasser", "Warmwasser"),
    "zirkulation": (0x2200, "zirkulation", "Zirkulation"),
}
HK_BASE = {"hk1": 0x3000, "hk2": 0x4000}
RUNTIME = {  # key -> (topic of the on/off state, device key, entity name, max gap in seconds)
    "brenner": ("brennermodulation", "brenner", "Laufzeit heute", 30),
    "interne_kesselpumpe": ("interne_kesselpumpe", "kessel", "Interne Kesselpumpe Laufzeit heute", 120),
    "hk1_pumpe": ("hk1_pumpe", "heizkreis_1", "Umwälzpumpe Laufzeit heute", 120),
    "hk2_pumpe": ("hk2_pumpe", "heizkreis_2", "Umwälzpumpe Laufzeit heute", 120),
    "warmwasser_ladepumpe": ("warmwasser_ladepumpe", "warmwasser", "Ladepumpe Laufzeit heute", 120),
    "zirkulationspumpe": ("zirkulationspumpe", "zirkulation", "Pumpe Laufzeit heute", 120),
    "solarpumpe": ("solarpumpe", "solar", "Kreispumpe Laufzeit heute", 120),
}
HOLIDAY_REGISTERS = (0x2309, 0x3309, 0x4309)
CYCLING_THRESHOLD = 4
HOLIDAY_UNSET = bytes.fromhex("19700101040000001970010104000000")
INPUTS = [  # splitter topics we need
    "brennermodulation", "brennerstarts", "brennerlaufzeit", "aussentemperatur", "aussentemperatur_gemischt", "sammelstoerung",
    "solar_kollektortemperatur", "solar_speichertemperatur",
    "urlaubsprogramm_beginn", "urlaubsprogramm_ende",
    "interne_kesselpumpe", "warmwasser_ladepumpe", "zirkulationspumpe", "solarpumpe",
] + [f"hk{n}_{x}" for n in (1, 2) for x in (
    "pumpe", "vorlauftemperatur", "raumsolltemperatur_aktuell", "normaltemperatur", "reduzierte_temperatur",
    "komforttemperatur", "heizkurve_steigung", "heizkurve_niveau", "betriebsart", "programm", "partybetrieb", "sparbetrieb",
    "zeitprogramm_roh_1", "zeitprogramm_roh_2")] + [
    f"{s}_zeitprogramm_roh_{i}" for s in ("warmwasser", "zirkulation") for i in (1, 2)]


# --------------------------------------------------------------------------------------------------------------
# persistent state
# --------------------------------------------------------------------------------------------------------------
class State:
    def __init__(self, path):
        self.path = path
        self.lock = threading.RLock()
        self.dirty = False
        self.data = {"v": 1, "boost_dauer": {}, "names": {"hk1": "Fußbodenheizung", "hk2": "Heizkörper"},
                     "overrides": {}, "burner": {}, "starts": {"events": []}, "runtime": {}, "backup": {}, "sync": {}}
        try:
            with open(path) as f:
                self.data.update(json.load(f))
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            log.exception("state file unreadable, starting empty (a copy is kept as .broken)")
            try:
                os.replace(path, path + ".broken")
            except OSError:
                pass

    def save(self, force=False):
        with self.lock:
            if not (self.dirty or force):
                return
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.data, f, indent=1)
            os.replace(tmp, self.path)
            self.dirty = False

    def touch(self):
        self.dirty = True


# --------------------------------------------------------------------------------------------------------------
# entity definitions for the discovery
# --------------------------------------------------------------------------------------------------------------
def device_cfg(key):
    if key is None:
        return POLL["device"]
    dev = dict(DEVICES[key])
    dev.setdefault("via_device", MAIN_ID)
    return dev


def entity_defs():
    """(domain, dp name, config) of every entity this service provides."""
    defs = []

    def add(domain, name, device, label, **cfg):
        defs.append((domain, name, dict(name=label, device=device_cfg(device), **cfg)))

    mins = dict(unit_of_measurement="min", device_class="duration", state_class="measurement")
    hours = dict(unit_of_measurement="h", device_class="duration", state_class="total_increasing",
                 suggested_display_precision=2)
    temp = dict(unit_of_measurement="°C", device_class="temperature", state_class="measurement",
                suggested_display_precision=1)

    # burner (own device below the installation, like the cloud grouped it, but separate from the boiler's temperatures)
    diag = dict(entity_category="diagnostic")
    add("binary_sensor", "brenner_taktung", "brenner", "Taktung", icon="mdi:sine-wave", device_class="problem",
        state_topic=f"{EXT}/brenner_taktung")
    add("sensor", "brenner_starts_heute", "brenner", "Starts heute", icon="mdi:counter",
        state_class="total_increasing", state_topic=f"{EXT}/brenner_starts_heute")
    add("sensor", "brenner_starts_letzte_stunde", "brenner", "Starts letzte Stunde", icon="mdi:counter",
        state_class="measurement", state_topic=f"{EXT}/brenner_starts_letzte_stunde", **diag)
    add("sensor", "brenner_letzte_laufzeit", "brenner", "Letzte Laufzeit", icon="mdi:timer-play-outline",
        suggested_display_precision=1, state_topic=f"{EXT}/brenner_letzte_laufzeit", **mins, **diag)
    add("sensor", "brenner_letzte_pause", "brenner", "Letzte Pause", icon="mdi:timer-pause-outline",
        suggested_display_precision=1, state_topic=f"{EXT}/brenner_letzte_pause", **mins, **diag)
    add("sensor", "brenner_laufzeit_pro_start", "brenner", "Ø Laufzeit pro Start", icon="mdi:timer-sand",
        suggested_display_precision=1, state_topic=f"{EXT}/brenner_laufzeit_pro_start", **mins, **diag)
    for prefix, label in (("brenner_automatik", "Automatik"), ("brenner_fehlerstatus", "Fehlerstatus")):
        add("sensor", prefix, "brenner", label, icon="mdi:check-network-outline", state_topic=f"{EXT}/{prefix}", **diag)
        add("sensor", prefix + "_fehlercode", "brenner", label + " Fehlercode", icon="mdi:alert-circle-outline",
            state_topic=f"{EXT}/{prefix}_fehlercode", **diag)
        add("sensor", prefix + "_fehlerdetails", "brenner", label + " Fehlerdetails", icon="mdi:alert-circle-outline",
            state_topic=f"{EXT}/{prefix}_fehlerdetails", **diag)
    # run time today
    for key, (_, device, label, _) in RUNTIME.items():
        name = "brenner_laufzeit_heute" if key == "brenner" else f"{key}_laufzeit_heute"
        add("sensor", name, device, label, icon="mdi:timer-outline", state_topic=f"{EXT}/{name}", **hours,
            **({} if key == "brenner" else diag))
    # heating circuits
    for n in (1, 2):
        hk = f"hk{n}"
        device = f"heizkreis_{n}"
        add("sensor", f"{hk}_soll_vorlauftemperatur_heizkurve", device, "Vorlauf Soll (Heizkurve)",
            icon="mdi:chart-bell-curve-cumulative", state_topic=f"{EXT}/{hk}_soll_vorlauftemperatur_heizkurve", **temp, **diag)
        add("sensor", f"{hk}_vorlauf_abweichung_zur_heizkurve", device, "Vorlauf Abweichung (Heizkurve)",
            icon="mdi:chart-bell-curve-cumulative", unit_of_measurement="K", state_class="measurement",
            suggested_display_precision=1, state_topic=f"{EXT}/{hk}_vorlauf_abweichung_zur_heizkurve", **diag)
        add("sensor", f"{hk}_programm", device, "Aktiver Heizmodus", icon="mdi:format-list-bulleted-type",
            state_topic=f"{EXT}/{hk}_programm")
        add("binary_sensor", f"{hk}_zeitprogramm_aktiv", device, "Zeitprogramm", icon="mdi:calendar-check",
            state_topic=f"{EXT}/{hk}_zeitprogramm_aktiv")
        for name, label, icon in (("komfortbetrieb", "Komfortbetrieb", "mdi:sofa"), ("sparbetrieb", "Sparbetrieb", "mdi:leaf")):
            add("switch", f"{hk}_{name}", device, label, icon=icon, state_topic=f"{EXT}/{hk}_{name}",
                command_topic=f"{EXT}/{hk}_{name}/set")
        add("text", f"{hk}_name", device, "Name", icon="mdi:rename-outline", entity_category="config",
            state_topic=f"{EXT}/{hk}_name", command_topic=f"{EXT}/{hk}_name/set", max=40)
    # time programs + overrides
    for key, (_, device, label) in SCHEDULES.items():
        enum = ["normal", "reduced"] if key.startswith("hk") else ["on", "off"]
        add("sensor", f"{key}_zeitprogramm", device, "Zeitplan (aktuelle Phase)" if key.startswith("hk") else "Zeitplan (aktuell)",
            icon="mdi:calendar-clock", device_class="enum", options=enum, state_topic=f"{EXT}/{key}_zeitprogramm",
            json_attributes_topic=f"{EXT}/{key}_zeitprogramm/attr", **diag)
        if key.startswith("hk"):    # the heating circuits have the operating mode and comfort / eco like the ViCare app
            continue                # instead of the boost / permanent operation of the old custom integration (time program rewrite)
        pump = key == "zirkulation"
        what = "Zusatzlauf" if pump else "Zusatzaufheizung"
        add("binary_sensor", f"{key}_zeitprogramm_aktiv", device, "Zeitprogramm", icon="mdi:calendar-check",
            state_topic=f"{EXT}/{key}_zeitprogramm_aktiv")
        add("button", f"{key}_boost", device, f"{what} starten", icon="mdi:rocket-launch",
            command_topic=f"{EXT}/{key}_boost/press", payload_press="PRESS")
        add("number", f"{key}_boost_dauer", device, f"Dauer {what}",
            icon="mdi:timer-cog-outline", entity_category="config", min=10, max=360, step=10, mode="box",
            unit_of_measurement="min", state_topic=f"{EXT}/{key}_boost_dauer", command_topic=f"{EXT}/{key}_boost_dauer/set")
        add("switch", f"{key}_dauerbetrieb", device, "Dauerbetrieb (Zeitprogramm überbrückt)",
            icon="mdi:calendar-lock", state_topic=f"{EXT}/{key}_dauerbetrieb", command_topic=f"{EXT}/{key}_dauerbetrieb/set")
        add("button", f"{key}_zeitprogramm_zuruecksetzen", device, "Überbrückung beenden",
            icon="mdi:calendar-refresh", command_topic=f"{EXT}/{key}_zeitprogramm_zuruecksetzen/press", payload_press="PRESS")
    # solar, holiday
    add("sensor", "solar_temperaturdifferenz_kollektor_speicher", "solar", "Temperaturdifferenz Kollektor/Speicher",
        icon="mdi:delta", unit_of_measurement="K", state_class="measurement", suggested_display_precision=1,
        state_topic=f"{EXT}/solar_temperaturdifferenz_kollektor_speicher")
    add("sensor", "fehlerhistorie", "anlage", "Letzter Fehler", icon="mdi:alert-circle-outline", entity_category="diagnostic",
        state_topic=f"{EXT}/fehlerhistorie", json_attributes_topic=f"{EXT}/fehlerhistorie/attr")
    add("binary_sensor", "urlaubsprogramm", "anlage", "Urlaubsprogramm", icon="mdi:airplane",
        state_topic=f"{EXT}/urlaubsprogramm")
    add("button", "urlaubsprogramm_beenden", "anlage", "Urlaubsprogramm beenden", icon="mdi:airplane-off",
        command_topic=f"{EXT}/urlaubsprogramm_beenden/press", payload_press="PRESS")
    return defs


# --------------------------------------------------------------------------------------------------------------
# the service
# --------------------------------------------------------------------------------------------------------------
def _locked(fn):
    """Serialise everything that reads or rewrites time programs (boost, permanent operation, restore, schedule sync)."""
    def wrapper(self, *args, **kwargs):
        with self.sched_lock:
            return fn(self, *args, **kwargs)
    wrapper.__name__ = fn.__name__
    return wrapper


class Extras:
    def __init__(self):
        self.state = State(STATE_FILE)
        self.values = {}                  # last payload of every splitter topic we listen to
        self.published = {}               # last payload we published per ext topic
        self.runtime_prev = {}            # key -> (is_on, timestamp)
        self.client = None
        self.stop = threading.Event()
        self.jobs = queue.Queue()
        self.cmd_lock = threading.Lock()
        self.resp_event = threading.Event()
        self.resp = None
        self.expect = None
        self.last_flush = time.time()
        self.fault_code = None
        self.sched_lock = threading.RLock()
        self.sync_hold = {}                 # key -> timestamp until which the sync skips that time program
        self.switch_hold = {}               # circuit -> timestamp until which a polled flag does not override a shown command
        self.sync_error_logged = 0.0

    # ---------------- mqtt ----------------
    def start(self):
        host, port = settings.mqtt_broker.split(":")
        self.client = paho.Client(paho.CallbackAPIVersion.VERSION2, "vito_extras")
        if settings.mqtt_user and str(settings.mqtt_user).lower() != "none":
            user, password = str(settings.mqtt_user).split(":", 1)
            self.client.username_pw_set(user, password)
        self.client.will_set(f"{EXT}/LWT", "offline", retain=True)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.reconnect_delay_set(2, 60)
        self.client.connect_async(host, int(port), 60)
        self.client.loop_start()
        threading.Thread(target=self.worker, daemon=True, name="jobs").start()
        threading.Thread(target=self.ticker, daemon=True, name="ticker").start()

    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        log.info("MQTT connected (%s)", reason_code)
        subs = [(f"{BASE}/{t}", 0) for t in INPUTS] + [(f"{BASE}/LWT", 0), (settings.mqtt_respond, 0),
                                                       (f"{EXT}/+/set", 0), (f"{EXT}/+/press", 0)]
        client.subscribe(subs)
        client.publish(f"{EXT}/LWT", "online", retain=True)
        self.publish_discovery()
        self.publish_static()

    def pub(self, topic, payload, retain=True, force=False):
        payload = payload if isinstance(payload, str) else json.dumps(payload) if isinstance(payload, (dict, list)) else str(payload)
        if not force and self.published.get(topic) == payload:
            return
        self.published[topic] = payload
        if self.client:
            self.client.publish(topic, payload, retain=retain)

    def publish_discovery(self):
        avail = [{"topic": f"{BASE}/LWT"}, {"topic": f"{EXT}/LWT"}]
        for domain, name, cfg in entity_defs():
            cfg = dict(cfg)
            cfg.update(unique_id=f"{PREFIX}{name}", default_entity_id=f"{domain}.{PREFIX}{name}",
                       availability=avail, availability_mode="all")
            self.client.publish(f"{HA_PREFIX}/{domain}/{NODE}/{name}/config", json.dumps(cfg), retain=True)
        for domain, name in OBSOLETE_DISCOVERY:                      # entities that were replaced, drop their retained config
            self.client.publish(f"{HA_PREFIX}/{domain}/{NODE}/{name}/config", "", retain=True)
        log.info("discovery published (%d entities)", len(entity_defs()))

    def publish_static(self):
        with self.state.lock:
            for key in SCHEDULES:
                self.pub(f"{EXT}/{key}_boost_dauer", self.state.data["boost_dauer"].get(key, 30), force=True)
                self.pub(f"{EXT}/{key}_dauerbetrieb", "ON" if self.override_kind(key) == "permanent" else "OFF", force=True)
            for hk, text in self.state.data["names"].items():
                self.pub(f"{EXT}/{hk}_name", text, force=True)
        for key in list(self.values):
            self.recompute(key, time.time(), fresh=False)

    def on_message(self, client, userdata, msg):
        try:
            payload = msg.payload.decode(errors="replace").strip()
            topic = msg.topic
            if topic == settings.mqtt_respond:
                return self.on_response(payload)
            if topic.startswith(EXT + "/"):
                return self.on_command(topic[len(EXT) + 1:], payload)
            name = topic[len(BASE) + 1:]
            if name == "LWT":
                return
            self.values[name] = payload
            self.recompute(name, time.time(), fresh=not msg.retain)
        except Exception:
            log.exception("error handling %s", msg.topic)

    # ---------------- optolink access ----------------
    def on_response(self, payload):
        parts = payload.split(";", 2)
        if len(parts) < 3 or self.expect is None:
            return
        try:
            addr = int(parts[1], 0)
        except ValueError:
            return
        if addr == self.expect:
            self.resp = (parts[0], parts[2])
            self.resp_event.set()

    def opto(self, cmd, addr, timeout=10):
        """Send one command to the splitter and wait for its answer. Returns the value part of the response."""
        with self.cmd_lock:
            self.resp, self.expect = None, addr
            self.resp_event.clear()
            self.client.publish(settings.mqtt_listen, cmd)
            if not self.resp_event.wait(timeout):
                self.expect = None
                raise TimeoutError(f"no answer to '{cmd}'")
            self.expect = None
            rc, value = self.resp
            if rc.strip() not in ("1", "01"):
                raise RuntimeError(f"'{cmd}' failed: {rc};{value}")
            return value

    @staticmethod
    def write_allowed(addr, length):
        for base in HK_BASE.values():
            if length == 1 and addr in (base + 0x306, base + 0x307, base + 0x308, base + 0x330, base + 0x331):
                return True
        for base, _, _ in SCHEDULES.values():
            if length == 8 and base <= addr < base + 56 and (addr - base) % 8 == 0:
                return True
        return length == 16 and addr in HOLIDAY_REGISTERS

    def write(self, addr, data):
        """data: int (1 byte) or bytes. Whitelisted registers only; time programs are read back."""
        raw = bytes([data]) if isinstance(data, int) else bytes(data)
        if not self.write_allowed(addr, len(raw)):
            raise PermissionError(f"write to 0x{addr:04x} ({len(raw)} byte) is not allowed")
        if len(raw) == 1:
            self.opto(f"write;0x{addr:04x};1;{raw[0]}", addr)
        else:
            self.opto(f"writeraw;0x{addr:04x};{raw.hex()}", addr)
        if len(raw) == 8:
            back = bytes.fromhex(self.opto(f"read;0x{addr:04x};8;raw", addr))
            if back != raw:
                raise RuntimeError(f"read back of 0x{addr:04x} differs: wrote {raw.hex()}, read {back.hex()}")

    def read_hex(self, addr, length):
        return bytes.fromhex(self.opto(f"read;0x{addr:04x};{length};raw", addr))

    def forcepoll(self):
        self.client.publish(settings.mqtt_listen, "forcepoll")

    # ---------------- commands from Home Assistant ----------------
    def on_command(self, rest, payload):
        self.jobs.put((rest, payload))

    def worker(self):
        while not self.stop.is_set():
            try:
                rest, payload = self.jobs.get(timeout=1)
            except queue.Empty:
                continue
            try:
                self.handle_command(rest, payload)
            except Exception as err:
                log.error("command %s=%s failed: %s", rest, payload, err)

    def handle_command(self, rest, payload):
        name, _, action = rest.rpartition("/")
        if rest == "_faulthistory":
            return self.fault_history()
        if rest == "_faultcode":
            self.fault_code = self.read_hex(0x7507, 1)[0]      # most recent entry of the fault history
            return self.fault(self.values.get("sammelstoerung") == "ON")
        log.info("command %s %s", rest, payload)
        if name in ("hk1_temperatur", "hk2_temperatur"):
            return self.set_temperature(name[:3], payload)
        if name in ("hk1_preset", "hk2_preset"):
            return self.set_preset(name[:3], payload)
        if name in ("hk1_komfortbetrieb", "hk2_komfortbetrieb", "hk1_sparbetrieb", "hk2_sparbetrieb"):
            return self.set_program_switch(name[:3], name[4:], payload.upper() == "ON")
        if name.endswith("_name") and name[:3] in ("hk1", "hk2"):
            with self.state.lock:
                self.state.data["names"][name[:3]] = payload[:40]
                self.state.touch()
            return self.pub(f"{EXT}/{name}", payload[:40], force=True)
        if name == "urlaubsprogramm_beenden":
            return self.end_holiday()
        for key in SCHEDULES:
            if name == f"{key}_boost_dauer":
                minutes = max(10, min(360, int(round(float(payload) / 10.0)) * 10))
                with self.state.lock:
                    self.state.data["boost_dauer"][key] = minutes
                    self.state.touch()
                return self.pub(f"{EXT}/{name}", minutes, force=True)
            if name == f"{key}_boost":
                return self.boost(key)
            if name == f"{key}_dauerbetrieb":
                return self.permanent(key, payload.upper() == "ON")
            if name == f"{key}_zeitprogramm_zuruecksetzen":
                return self.restore_schedule(key, "manual reset")

    def set_temperature(self, hk, payload):
        value = int(round(float(payload)))
        if not 3 <= value <= 37:
            raise ValueError(f"set point {value} outside 3..37")
        party = self.values.get(f"{hk}_partybetrieb") == "ON"
        offset = logic.program_register_offset(logic.program_name(self.values.get(f"{hk}_programm")), party)
        self.write(HK_BASE[hk] + offset, value)
        self.forcepoll()

    def set_preset(self, hk, preset):
        if preset not in ("comfort", "eco", "home", "sleep", "none"):
            raise ValueError(f"unknown preset {preset}")
        base = HK_BASE[hk]
        # Comfort and eco are switched with the command registers 0x330 / 0x331, exactly what the ViCare app writes
        # (the flags 0x303 / 0x302 are only their status; a direct write is cleared again by the controller). Both
        # commands are always written (idempotent): the cached state may be up to a poll cycle old. Like the ViCare
        # integration, the other program is switched off before the wanted one is switched on. Eco only holds in a
        # normal phase of the time program, in a reduced phase the controller takes it back within seconds.
        self.write(base + 0x331, 0)
        self.write(base + 0x330, 0)
        if preset == "comfort":
            self.write(base + 0x330, 1)
        elif preset == "eco":
            self.write(base + 0x331, 1)
        self.forcepoll()

    def program_switches(self, hk):
        """State of the switches Komfortbetrieb / Sparbetrieb from the status flags the controller sets (0x?303 / 0x?302)."""
        if time.time() < self.switch_hold.get(hk, 0):
            return
        for name, flag in (("komfortbetrieb", "partybetrieb"), ("sparbetrieb", "sparbetrieb")):
            if f"{hk}_{flag}" in self.values:
                self.pub(f"{EXT}/{hk}_{name}", "ON" if self.values.get(f"{hk}_{flag}") == "ON" else "OFF")

    def set_program_switch(self, hk, name, on):
        """Comfort / eco on or off with the command registers 0x?330 / 0x?331, like the ViCare app. Activating one cancels the other."""
        base = HK_BASE[hk]
        mine, other = (base + 0x330, base + 0x331) if name == "komfortbetrieb" else (base + 0x331, base + 0x330)
        if on:
            self.write(other, 0)
        self.write(mine, 1 if on else 0)
        self.forcepoll()
        # Show the expected state at once: the controller sets its status flag only after a few seconds. The next poll
        # confirms it or corrects it (in a reduced phase the controller takes eco back).
        self.switch_hold[hk] = time.time() + SWITCH_HOLD
        self.pub(f"{EXT}/{hk}_{name}", "ON" if on else "OFF", force=True)
        if on:
            self.pub(f"{EXT}/{hk}_{'sparbetrieb' if name == 'komfortbetrieb' else 'komfortbetrieb'}", "OFF", force=True)

    def end_holiday(self):
        for addr in HOLIDAY_REGISTERS[1:]:          # M2 and M3 (M1 is unused)
            self.write(addr, HOLIDAY_UNSET)
        self.forcepoll()

    # ---------------- time program overrides ----------------
    def override_kind(self, key):
        return (self.state.data["overrides"].get(key) or {}).get("kind")

    def read_week(self, key):
        base = SCHEDULES[key][0]
        return b"".join(self.read_hex(base + 8 * d, 8) for d in range(7))

    def backup_schedules(self):
        """One-time snapshot of all time programs (kept in the state file)."""
        with self.state.lock:
            if self.state.data["backup"].get("weeks"):
                return
        weeks = {key: self.read_week(key).hex() for key in SCHEDULES}
        with self.state.lock:
            self.state.data["backup"] = {"taken": datetime.now().isoformat(timespec="seconds"), "weeks": weeks}
            self.state.touch()
            self.state.save()
        log.info("time programs backed up in %s", STATE_FILE)

    @_locked
    def boost(self, key):
        base = SCHEDULES[key][0]
        with self.state.lock:
            current = self.state.data["overrides"].get(key)
            if current and current["kind"] == "permanent":
                raise RuntimeError(f"{key}: permanent operation is active, boost refused")
            minutes = int(self.state.data["boost_dauer"].get(key, 30))
        now = datetime.now()
        day = now.weekday()
        addr = base + 8 * day
        live = self.read_hex(addr, 8)
        original = bytes.fromhex(current["original_day"]) if current and current.get("day") == day else live
        new_day, end = logic.add_boost(original, now.hour * 60 + now.minute, minutes)
        until = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(minutes=end)
        if current and current.get("day") == day:
            until = max(until, datetime.fromtimestamp(current["until"]))
        with self.state.lock:                                   # persist the original BEFORE writing
            self.state.data["overrides"][key] = {"kind": "boost", "day": day, "original_day": original.hex(),
                                                 "until": until.timestamp()}
            self.state.touch()
            self.state.save()
        try:
            self.write(addr, new_day)
        except Exception:
            log.error("boost write failed, restoring %s", key)
            self.restore_schedule(key, "boost write failed")
            raise
        log.info("%s boost until %s: %s -> %s", key, until.strftime("%H:%M"), logic.format_slots(original),
                 logic.format_slots(new_day))
        self.after_override(key)

    @_locked
    def permanent(self, key, on):
        base = SCHEDULES[key][0]
        if not on:
            if self.override_kind(key) == "permanent":
                self.restore_schedule(key, "permanent operation switched off")
            return self.after_override(key)
        with self.state.lock:
            current = self.state.data["overrides"].get(key)
        if current and current["kind"] == "boost":
            self.restore_schedule(key, "replaced by permanent operation")
        week = self.read_week(key)
        with self.state.lock:
            self.state.data["overrides"][key] = {"kind": "permanent", "original_week": week.hex()}
            self.state.touch()
            self.state.save()
        try:
            for d in range(7):
                self.write(base + 8 * d, logic.permanent_day())
        except Exception:
            log.error("permanent write failed, restoring %s", key)
            self.restore_schedule(key, "permanent write failed")
            raise
        log.info("%s permanent operation on", key)
        self.after_override(key)

    @_locked
    def restore_schedule(self, key, reason):
        base = SCHEDULES[key][0]
        with self.state.lock:
            current = self.state.data["overrides"].get(key)
        if not current:
            return log.info("%s: nothing to restore (%s)", key, reason)
        if current["kind"] == "boost":
            self.write(base + 8 * current["day"], bytes.fromhex(current["original_day"]))
        else:
            week = bytes.fromhex(current["original_week"])
            for d in range(7):
                self.write(base + 8 * d, week[8 * d:8 * d + 8])
        with self.state.lock:
            self.state.data["overrides"].pop(key, None)
            self.state.touch()
            self.state.save()
        log.info("%s restored (%s)", key, reason)
        self.after_override(key)

    def after_override(self, key):
        self.pub(f"{EXT}/{key}_dauerbetrieb", "ON" if self.override_kind(key) == "permanent" else "OFF")
        self.bridged_state(key)
        self.schedule_state(key, datetime.now())
        self.forcepoll()

    def check_overrides(self):
        now = time.time()
        for key, ov in list(self.state.data["overrides"].items()):
            if ov["kind"] == "boost" and now >= ov["until"]:
                try:
                    self.restore_schedule(key, "boost finished")
                except Exception as err:
                    log.error("restore of %s failed, retrying: %s", key, err)

    # ---------------- schedule helper sync (Home Assistant <-> controller) ----------------
    def ha_config(self):
        """(url, token) from extras_config.json, or None when the sync is not configured."""
        try:
            with open(CONFIG_FILE) as f:
                cfg = json.load(f)
            token_file = cfg.get("ha_token_file", "ha_token")
            token_file = token_file if os.path.isabs(token_file) else os.path.join(ROOT, token_file)
            with open(token_file) as f:
                return cfg["ha_url"], f.read().strip()
        except (OSError, KeyError, ValueError):
            return None

    def effective_slots(self, key, week):
        """Slots of the controller's program as the user configured it, i.e. with an active boost / permanent override undone."""
        ov = self.state.data["overrides"].get(key)
        week = bytes(week) + bytes([logic.UNUSED] * max(0, 56 - len(week)))
        if ov and ov["kind"] == "permanent":
            week = bytes.fromhex(ov["original_week"])
        elif ov:
            week = week[:ov["day"] * 8] + bytes.fromhex(ov["original_day"]) + week[ov["day"] * 8 + 8:]
        return logic.week_to_slots(week)

    def raw_week(self, key):
        a, b = self.values.get(f"{key}_zeitprogramm_roh_1", ""), self.values.get(f"{key}_zeitprogramm_roh_2", "")
        return bytes.fromhex(a[:96] + b[:16]) if len(a) >= 96 and len(b) >= 16 else None

    def sync_schedules(self):
        cfg = self.ha_config()
        if cfg is None:
            return
        try:
            with HaClient(*cfg) as ha:
                helpers = {h["name"]: h for h in ha.call({"type": "schedule/list"})}
                for key in SCHEDULES:
                    if time.time() >= self.sync_hold.get(key, 0):
                        self.sync_one(ha, key, helpers.get(SCHEDULE_HELPERS[key][0]))
        except (OSError, HaError) as err:
            if time.time() - self.sync_error_logged > 600:
                self.sync_error_logged = time.time()
                log.warning("schedule sync: Home Assistant not reachable or request failed: %s", err)

    def helper_payload(self, key, slots):
        name, icon = SCHEDULE_HELPERS[key]
        return {"name": name, "icon": icon, **logic.slots_to_helper(slots)}

    @_locked
    def sync_one(self, ha, key, helper):
        raw = self.raw_week(key)
        if raw is None:
            return
        device = self.effective_slots(key, raw)
        with self.state.lock:
            saved = self.state.data["sync"].get(key)
        baseline = [[tuple(x) for x in day] for day in saved] if saved else None
        if helper is None:                                           # first run: create the helper from the controller
            ha.call({"type": "schedule/create", **self.helper_payload(key, device)})
            self.set_baseline(key, device)
            return log.info("schedule sync: created helper for %s", key)
        wanted = logic.helper_to_slots(helper)
        decision = logic.sync_decision(baseline, wanted, device)
        if decision == "none":
            if baseline != device:
                self.set_baseline(key, device)
            return
        # polled values can be up to one poll cycle old: confirm with a fresh read before acting
        device = self.effective_slots(key, self.read_week(key))
        decision = logic.sync_decision(baseline, wanted, device)
        if decision == "none":
            return self.set_baseline(key, device)
        if decision == "to_device":
            try:
                self.apply_to_device(key, wanted)
            except ValueError as err:
                log.warning("schedule sync: %s rejected (%s), helper reverted", key, err)
                self.notify(ha, key, f"Das Zeitprogramm wurde nicht übernommen: {err}. Der Zeitplan wurde auf den Stand des Reglers zurückgesetzt.")
                decision = "to_helper"
            else:
                self.set_baseline(key, wanted)
                self.sync_hold[key] = time.time() + 90                  # polled values catch up after the next poll
                if logic.slots_to_helper(wanted) != {d: helper.get(d, []) for d in logic.WEEKDAYS}:   # snapped to the 10 minute raster
                    ha.call({"type": "schedule/update", "schedule_id": helper["id"], **self.helper_payload(key, wanted)})
                return log.info("schedule sync: %s helper -> controller", key)
        if decision in ("to_helper", "conflict"):
            ha.call({"type": "schedule/update", "schedule_id": helper["id"], **self.helper_payload(key, device)})
            self.set_baseline(key, device)
            if decision == "conflict":
                log.warning("schedule sync: %s changed on both sides, the controller wins", key)
                self.notify(ha, key, "Zeitprogramm wurde gleichzeitig in Home Assistant und am Regler geändert. Der Stand des Reglers wurde übernommen.")
            else:
                log.info("schedule sync: %s controller -> helper", key)

    def set_baseline(self, key, slots):
        with self.state.lock:
            self.state.data["sync"][key] = [[list(x) for x in day] for day in slots]
            self.state.touch()

    def apply_to_device(self, key, wanted):
        """Write the helper's program to the controller; with an active override only the stored original is changed."""
        week = logic.slots_to_week(wanted)                              # raises ValueError for more than 4 periods per day
        base = SCHEDULES[key][0]
        with self.state.lock:
            ov = self.state.data["overrides"].get(key)
        if ov and ov["kind"] == "permanent":
            ov["original_week"] = week.hex()
        else:
            live = logic.week_to_slots(self.read_week(key))
            for day in range(7):
                if ov and ov["day"] == day:
                    ov["original_day"] = week[day * 8:day * 8 + 8].hex()      # restored when the boost ends
                elif live[day] != wanted[day]:
                    self.write(base + 8 * day, week[day * 8:day * 8 + 8])
        if ov:
            with self.state.lock:
                self.state.touch()
                self.state.save()
        self.forcepoll()

    def notify(self, ha, key, message):
        try:
            ha.call({"type": "call_service", "domain": "persistent_notification", "service": "create",
                     "service_data": {"title": f"Heizung Zeitprogramm ({key})", "message": message, "notification_id": f"vito_sync_{key}"}})
        except HaError:
            pass

    # ---------------- derived values ----------------
    def num(self, name):
        try:
            return float(self.values[name])
        except (KeyError, ValueError):
            return None

    def recompute(self, name, ts, fresh=True):
        now = datetime.fromtimestamp(ts)
        if name == "brennermodulation":
            self.burner(now, ts, fresh)
        if name == "brennerstarts":
            self.starts(now, ts, fresh)
        for key, (topic, _, _, cap) in RUNTIME.items():
            if name == topic:
                value = self.values.get(topic, "")
                on = (self.num(topic) or 0) > 0 if key == "brenner" else value == "ON"
                self.runtime(key, on, ts, cap, fresh)
        if name in ("brennerlaufzeit", "brennerstarts"):
            hours, starts = self.num("brennerlaufzeit"), self.num("brennerstarts")
            if hours is not None and starts:
                self.pub(f"{EXT}/brenner_laufzeit_pro_start", round(hours * 60 / starts, 1))
        if name == "sammelstoerung":
            self.fault(self.values.get(name) == "ON")
        if name in ("aussentemperatur", "aussentemperatur_gemischt") or name.startswith(("hk1_", "hk2_")):
            for hk in ("hk1", "hk2"):
                self.curve(hk)
                self.preset(hk)
                self.heizmodus(hk)
                self.program_switches(hk)
        if name in ("solar_kollektortemperatur", "solar_speichertemperatur"):
            k, s = self.num("solar_kollektortemperatur"), self.num("solar_speichertemperatur")
            if k is not None and s is not None:
                self.pub(f"{EXT}/solar_temperaturdifferenz_kollektor_speicher", round(k - s, 1))
        if name.startswith(("urlaubsprogramm_",)):
            self.holiday(now)
        if "_zeitprogramm_roh_" in name:
            self.schedule_state(name.split("_zeitprogramm_roh_")[0], now)

    def runtime(self, key, on, ts, cap, fresh):
        with self.state.lock:
            rt = self.state.data["runtime"]
            day = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            if rt.get("day") != day:
                rt.clear()
                rt["day"] = day
            prev = self.runtime_prev.get(key)
            if prev and fresh:
                prev_on, prev_ts = prev
                midnight = datetime.fromtimestamp(ts).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
                span = ts - max(prev_ts, midnight)
                if prev_on and 0 < span <= cap * 3:
                    rt[key] = rt.get(key, 0.0) + span
                    self.state.touch()
            self.runtime_prev[key] = (on, ts)
            seconds = rt.get(key, 0.0)
        name = "brenner_laufzeit_heute" if key == "brenner" else f"{key}_laufzeit_heute"
        self.pub(f"{EXT}/{name}", round(seconds / 3600, 3))

    def burner(self, now, ts, fresh):
        on = (self.num("brennermodulation") or 0) > 0
        with self.state.lock:
            b = self.state.data["burner"]
            if "on" not in b:
                b.update(on=on, since=ts)
            elif fresh and on != b["on"]:
                minutes = round((ts - b["since"]) / 60, 1)
                b["last_run" if b["on"] else "last_pause"] = minutes
                b.update(on=on, since=ts)
                self.state.touch()
            elif not fresh:
                b.setdefault("on", on)
            last_run, last_pause = b.get("last_run"), b.get("last_pause")
        if last_run is not None:
            self.pub(f"{EXT}/brenner_letzte_laufzeit", last_run)
        if last_pause is not None:
            self.pub(f"{EXT}/brenner_letzte_pause", last_pause)

    def starts(self, now, ts, fresh):
        counter = self.num("brennerstarts")
        if counter is None:
            return
        counter = int(counter)
        today = now.strftime("%Y-%m-%d")
        with self.state.lock:
            s = self.state.data["starts"]
            last = s.get("last")
            if s.get("day") != today:
                s["baseline"] = last if last is not None else counter
                s["day"] = today
            if last is not None and 0 < counter - last <= 10 and fresh:
                s.setdefault("events", []).extend([ts] * (counter - last))
            s["last"] = counter
            s["events"] = [e for e in s.get("events", []) if ts - e < 3600]
            self.state.touch()
            last_hour, today_count = len(s["events"]), counter - s["baseline"]
        self.pub(f"{EXT}/brenner_starts_letzte_stunde", last_hour)
        self.pub(f"{EXT}/brenner_starts_heute", today_count)
        self.pub(f"{EXT}/brenner_taktung", "ON" if last_hour >= CYCLING_THRESHOLD else "OFF")

    def fault(self, active):
        """No separate burner controller state is readable; derive it from the collective fault flag."""
        status = "error" if active else "ok"
        if active != getattr(self, "fault_active", None):
            self.fault_active = active
            self.jobs.put(("_faulthistory", ""))
        if not active:
            code, details = 0, "ok"
            self.fault_code = None
        else:
            code = getattr(self, "fault_code", None)
            if code is None:
                self.jobs.put(("_faultcode", ""))          # read in the worker, not in the MQTT callback thread
            code = "unknown" if code is None else code
            details = f"Fehlercode {code}"
        for prefix in ("brenner_automatik", "brenner_fehlerstatus"):
            self.pub(f"{EXT}/{prefix}", status)
            self.pub(f"{EXT}/{prefix}_fehlercode", code)
            self.pub(f"{EXT}/{prefix}_fehlerdetails", details)

    def fault_history(self):
        """The controller keeps the last 10 faults (code + time); the ViCare API only shows the current status."""
        entries = []
        for i in range(10):
            fault = logic.decode_fault(self.read_hex(0x7507 + 9 * i, 9))
            if fault:
                entries.append({"code": f"0x{fault[0]:02X}", "zeit": fault[1].isoformat(sep=" ")})
        state = f"{entries[0]['code']} ({entries[0]['zeit'][:10]})" if entries else "keine"
        self.pub(f"{EXT}/fehlerhistorie", state)
        self.pub(f"{EXT}/fehlerhistorie/attr", {"eintraege": entries, "anzahl": len(entries)})

    def curve(self, hk):
        outside = self.num("aussentemperatur_gemischt")          # the value the controller's heating curve works with
        if outside is None:
            outside = self.num("aussentemperatur")
        room = self.num(f"{hk}_raumsolltemperatur_aktuell")
        if room is None or room < 5:
            room = self.num(f"{hk}_normaltemperatur")
        target = logic.heating_curve_target(outside, room, self.num(f"{hk}_heizkurve_steigung"),
                                            self.num(f"{hk}_heizkurve_niveau"))
        if target is None:
            return
        self.pub(f"{EXT}/{hk}_soll_vorlauftemperatur_heizkurve", target)
        flow = self.num(f"{hk}_vorlauftemperatur")
        if flow is not None:
            self.pub(f"{EXT}/{hk}_vorlauf_abweichung_zur_heizkurve", round(flow - target, 1))

    def preset(self, hk):
        if f"{hk}_programm" not in self.values:
            return
        program = logic.program_name(self.values[f"{hk}_programm"])
        self.pub(f"{EXT}/{hk}_preset", logic.preset_from(program, self.values.get(f"{hk}_partybetrieb") == "ON",
                                                        self.values.get(f"{hk}_sparbetrieb") == "ON"))

    def heizmodus(self, hk):
        """"Aktiver Heizmodus" like the ViCare app (Aus, Normal, Reduziert, Komfortbetrieb, Sparbetrieb, or the phase of the
        time program with its end) and whether the time program controls the circuit ("Zeitprogramm" on / off)."""
        mode, program = self.values.get(f"{hk}_betriebsart"), self.values.get(f"{hk}_programm")
        party, eco = self.values.get(f"{hk}_partybetrieb") == "ON", self.values.get(f"{hk}_sparbetrieb") == "ON"
        active = logic.zeitprogramm_aktiv(mode, party, eco)
        if active is not None:
            self.pub(f"{EXT}/{hk}_zeitprogramm_aktiv", "ON" if active else "OFF")
        if mode is None or program is None:
            return
        raw = self.raw_week(hk)
        until = logic.next_switch(logic.week_to_slots(raw), datetime.now()) if raw else None
        text = logic.heizmodus_text(mode, program, party, eco, until)
        if text:
            self.pub(f"{EXT}/{hk}_programm", text)

    def bridged_state(self, key):
        """DHW / circulation: the time program controls them unless a boost or permanent operation bridges it."""
        self.pub(f"{EXT}/{key}_zeitprogramm_aktiv", "OFF" if self.override_kind(key) else "ON")

    def holiday(self, now):
        start = logic.parse_vdatetime(self.values.get("urlaubsprogramm_beginn", ""))
        end = logic.parse_vdatetime(self.values.get("urlaubsprogramm_ende", ""))
        active = bool(start and end and start.date() <= now.date() <= end.date())
        self.pub(f"{EXT}/urlaubsprogramm", "ON" if active else "OFF")

    def schedule_state(self, key, now):
        if key not in SCHEDULES:
            return
        a, b = self.values.get(f"{key}_zeitprogramm_roh_1", ""), self.values.get(f"{key}_zeitprogramm_roh_2", "")
        if len(a) < 96 or len(b) < 16:
            return
        week = bytes.fromhex(a[:96] + b[:16])
        on = logic.is_active(week, now)
        state = ("normal" if on else "reduced") if key.startswith("hk") else ("on" if on else "off")
        ov = self.state.data["overrides"].get(key)
        attrs = {"heute": logic.format_slots(week[now.weekday() * 8: now.weekday() * 8 + 8]),
                 "override": ov["kind"] if ov else None,
                 "override_bis": datetime.fromtimestamp(ov["until"]).isoformat(timespec="minutes") if ov and "until" in ov else None}
        self.pub(f"{EXT}/{key}_zeitprogramm", state)
        self.pub(f"{EXT}/{key}_zeitprogramm/attr", attrs)

    # ---------------- housekeeping ----------------
    def ticker(self):
        time.sleep(15)
        last_history = 0.0
        last_sync = 0.0
        while not self.stop.wait(15):
            try:
                if time.time() - last_history > 6 * 3600:
                    last_history = time.time()
                    self.jobs.put(("_faulthistory", ""))
                if not self.state.data["backup"].get("weeks"):
                    try:
                        self.backup_schedules()
                    except Exception as err:
                        log.error("schedule backup failed, will retry: %s", err)
                now = datetime.now()
                for key in SCHEDULES:
                    self.schedule_state(key, now)
                for hk in ("hk1", "hk2"):
                    self.heizmodus(hk)
                for key in ("warmwasser", "zirkulation"):
                    self.bridged_state(key)
                self.holiday(now)
                self.check_overrides()
                if time.time() - last_sync > SYNC_INTERVAL:
                    last_sync = time.time()
                    self.sync_schedules()
                if time.time() - self.last_flush > 60:
                    self.state.save()
                    self.last_flush = time.time()
            except Exception:
                log.exception("ticker")

    def shutdown(self, *_):
        self.stop.set()
        self.state.save(force=True)
        if self.client:
            self.client.publish(f"{EXT}/LWT", "offline", retain=True).wait_for_publish(2)
            self.client.loop_stop()
            self.client.disconnect()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s]: %(message)s")
    service = Extras()
    signal.signal(signal.SIGTERM, service.shutdown)
    signal.signal(signal.SIGINT, service.shutdown)
    service.start()
    log.info("vito_extras running (splitter topic %s, own topic %s)", BASE, EXT)
    service.stop.wait()
    log.info("stopped")


if __name__ == "__main__":
    main()
