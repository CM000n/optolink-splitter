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
   * time program state of the heating circuits, DHW and circulation, active program, climate preset
   * holiday program state and "end holiday"
   * climate set point and preset commands (writes the register of the active program, party / eco flags)
   * boost and permanent operation of the four time programs (rewrites the time program, original is saved and
     restored; this is how the ViCare integration did it through the cloud)

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

# time programs: key -> (base address, device key, label)
SCHEDULES = {
    "hk1": (0x3000, "heizkreis_1", "Heizkreis 1"),
    "hk2": (0x4000, "heizkreis_2", "Heizkreis 2"),
    "warmwasser": (0x2100, "warmwasser", "Warmwasser"),
    "zirkulation": (0x2200, "zirkulation", "Zirkulation"),
}
HK_BASE = {"hk1": 0x3000, "hk2": 0x4000}
RUNTIME = {  # key -> (topic of the on/off state, device key, entity name, max gap in seconds)
    "brenner": ("brennermodulation", "kessel", "Brenner Laufzeit heute", 30),
    "interne_kesselpumpe": ("interne_kesselpumpe", "kessel", "Interne Kesselpumpe Laufzeit heute", 120),
    "hk1_pumpe": ("hk1_pumpe", "heizkreis_1", "Pumpe Laufzeit heute", 120),
    "hk2_pumpe": ("hk2_pumpe", "heizkreis_2", "Pumpe Laufzeit heute", 120),
    "warmwasser_ladepumpe": ("warmwasser_ladepumpe", "warmwasser", "Speicherladepumpe Laufzeit heute", 120),
    "zirkulationspumpe": ("zirkulationspumpe", "zirkulation", "Pumpe Laufzeit heute", 120),
    "solarpumpe": ("solarpumpe", "solar", "Kreispumpe Laufzeit heute", 120),
}
HOLIDAY_REGISTERS = (0x2309, 0x3309, 0x4309)
CYCLING_THRESHOLD = 4
HOLIDAY_UNSET = bytes.fromhex("19700101040000001970010104000000")
INPUTS = [  # splitter topics we need
    "brennermodulation", "brennerstarts", "brennerlaufzeit", "aussentemperatur", "sammelstoerung",
    "solar_kollektortemperatur", "solar_speichertemperatur",
    "urlaubsprogramm_beginn", "urlaubsprogramm_ende",
    "interne_kesselpumpe", "warmwasser_ladepumpe", "zirkulationspumpe", "solarpumpe",
] + [f"hk{n}_{x}" for n in (1, 2) for x in (
    "pumpe", "vorlauftemperatur", "raumsolltemperatur_aktuell", "normaltemperatur", "reduzierte_temperatur",
    "komforttemperatur", "heizkurve_steigung", "heizkurve_niveau", "programm", "partybetrieb", "sparbetrieb",
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
                     "overrides": {}, "burner": {}, "starts": {"events": []}, "runtime": {}, "backup": {}}
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

    # boiler
    add("binary_sensor", "brenner_taktung", "kessel", "Brenner Taktung", icon="mdi:sine-wave", device_class="problem",
        state_topic=f"{EXT}/brenner_taktung")
    add("sensor", "brenner_starts_heute", "kessel", "Brenner Starts heute", icon="mdi:counter",
        state_class="total_increasing", state_topic=f"{EXT}/brenner_starts_heute")
    add("sensor", "brenner_starts_letzte_stunde", "kessel", "Brenner Starts letzte Stunde", icon="mdi:counter",
        state_class="measurement", state_topic=f"{EXT}/brenner_starts_letzte_stunde")
    add("sensor", "brenner_letzte_laufzeit", "kessel", "Brenner letzte Laufzeit", icon="mdi:timer-play-outline",
        suggested_display_precision=1, state_topic=f"{EXT}/brenner_letzte_laufzeit", **mins)
    add("sensor", "brenner_letzte_pause", "kessel", "Brenner letzte Pause", icon="mdi:timer-pause-outline",
        suggested_display_precision=1, state_topic=f"{EXT}/brenner_letzte_pause", **mins)
    add("sensor", "brenner_laufzeit_pro_start", "kessel", "Brenner Ø Laufzeit pro Start", icon="mdi:timer-sand",
        suggested_display_precision=1, state_topic=f"{EXT}/brenner_laufzeit_pro_start", **mins)
    for prefix, label in (("brenner_automatik", "Brenner Automatik"), ("brenner_fehlerstatus", "Brenner Fehlerstatus")):
        add("sensor", prefix, "kessel", label, icon="mdi:check-network-outline", state_topic=f"{EXT}/{prefix}")
        add("sensor", prefix + "_fehlercode", "kessel", label + " Fehlercode", icon="mdi:alert-circle-outline",
            entity_category="diagnostic", state_topic=f"{EXT}/{prefix}_fehlercode")
        add("sensor", prefix + "_fehlerdetails", "kessel", label + " Fehlerdetails", icon="mdi:alert-circle-outline",
            entity_category="diagnostic", state_topic=f"{EXT}/{prefix}_fehlerdetails")
    # run time today
    for key, (_, device, label, _) in RUNTIME.items():
        name = "brenner_laufzeit_heute" if key == "brenner" else f"{key}_laufzeit_heute"
        add("sensor", name, device, label, icon="mdi:timer-outline", state_topic=f"{EXT}/{name}", **hours)
    # heating circuits
    for n in (1, 2):
        hk = f"hk{n}"
        device = f"heizkreis_{n}"
        add("sensor", f"{hk}_soll_vorlauftemperatur_heizkurve", device, "Soll-Vorlauftemperatur (Heizkurve)",
            icon="mdi:chart-bell-curve-cumulative", state_topic=f"{EXT}/{hk}_soll_vorlauftemperatur_heizkurve", **temp)
        add("sensor", f"{hk}_vorlauf_abweichung_zur_heizkurve", device, "Vorlauf Abweichung zur Heizkurve",
            icon="mdi:chart-bell-curve-cumulative", unit_of_measurement="K", state_class="measurement",
            suggested_display_precision=1, state_topic=f"{EXT}/{hk}_vorlauf_abweichung_zur_heizkurve")
        add("text", f"{hk}_name", device, "Name", icon="mdi:rename-outline", entity_category="config",
            state_topic=f"{EXT}/{hk}_name", command_topic=f"{EXT}/{hk}_name/set", max=40)
    # time programs + overrides
    for key, (_, device, label) in SCHEDULES.items():
        enum = ["normal", "reduced"] if key.startswith("hk") else ["on", "off"]
        add("sensor", f"{key}_zeitprogramm", device, "Zeitprogramm", icon="mdi:calendar-clock", device_class="enum",
            options=enum, state_topic=f"{EXT}/{key}_zeitprogramm", json_attributes_topic=f"{EXT}/{key}_zeitprogramm/attr")
        pump = key == "zirkulation"
        add("button", f"{key}_boost", device, "Pumpe Boost" if pump else "Boost", icon="mdi:rocket-launch",
            command_topic=f"{EXT}/{key}_boost/press", payload_press="PRESS")
        add("number", f"{key}_boost_dauer", device, "Pumpe Boost-Dauer" if pump else "Boost-Dauer",
            icon="mdi:timer-cog-outline", entity_category="config", min=10, max=360, step=10, mode="box",
            unit_of_measurement="min", state_topic=f"{EXT}/{key}_boost_dauer", command_topic=f"{EXT}/{key}_boost_dauer/set")
        add("switch", f"{key}_dauerbetrieb", device, "Pumpe Dauerbetrieb" if pump else "Dauerbetrieb",
            icon="mdi:calendar-lock", state_topic=f"{EXT}/{key}_dauerbetrieb", command_topic=f"{EXT}/{key}_dauerbetrieb/set")
        add("button", f"{key}_zeitprogramm_zuruecksetzen", device, "Zeitprogramm zurücksetzen",
            icon="mdi:calendar-refresh", command_topic=f"{EXT}/{key}_zeitprogramm_zuruecksetzen/press", payload_press="PRESS")
    # solar, holiday
    add("sensor", "solar_temperaturdifferenz_kollektor_speicher", "solar", "Temperaturdifferenz Kollektor/Speicher",
        icon="mdi:delta", unit_of_measurement="K", state_class="measurement", suggested_display_precision=1,
        state_topic=f"{EXT}/solar_temperaturdifferenz_kollektor_speicher")
    add("binary_sensor", "urlaubsprogramm", "anlage", "Urlaubsprogramm", icon="mdi:airplane",
        state_topic=f"{EXT}/urlaubsprogramm")
    add("button", "urlaubsprogramm_beenden", "anlage", "Urlaubsprogramm beenden", icon="mdi:airplane-off",
        command_topic=f"{EXT}/urlaubsprogramm_beenden/press", payload_press="PRESS")
    return defs


# --------------------------------------------------------------------------------------------------------------
# the service
# --------------------------------------------------------------------------------------------------------------
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
            if length == 1 and addr in (base + 0x302, base + 0x303, base + 0x306, base + 0x307, base + 0x308):
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
        if rest == "_faultcode":
            self.fault_code = self.read_hex(0x7507, 1)[0]      # most recent entry of the fault history
            return self.fault(self.values.get("sammelstoerung") == "ON")
        log.info("command %s %s", rest, payload)
        if name in ("hk1_temperatur", "hk2_temperatur"):
            return self.set_temperature(name[:3], payload)
        if name in ("hk1_preset", "hk2_preset"):
            return self.set_preset(name[:3], payload)
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
        party_on = self.values.get(f"{hk}_partybetrieb") == "ON"
        eco_on = self.values.get(f"{hk}_sparbetrieb") == "ON"
        want_party, want_eco = preset == "comfort", preset == "eco"
        # like the ViCare integration: switch the other program off first, then the wanted one on
        if eco_on and not want_eco:
            self.write(base + 0x302, 0)
        if party_on and not want_party:
            self.write(base + 0x303, 0)
        if want_party and not party_on:
            self.write(base + 0x303, 1)
        if want_eco and not eco_on:
            self.write(base + 0x302, 1)
        self.forcepoll()

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
        self.forcepoll()

    def check_overrides(self):
        now = time.time()
        for key, ov in list(self.state.data["overrides"].items()):
            if ov["kind"] == "boost" and now >= ov["until"]:
                try:
                    self.restore_schedule(key, "boost finished")
                except Exception as err:
                    log.error("restore of %s failed, retrying: %s", key, err)

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
        if name in ("aussentemperatur",) or name.startswith(("hk1_", "hk2_")):
            for hk in ("hk1", "hk2"):
                self.curve(hk)
                self.preset(hk)
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

    def curve(self, hk):
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
        while not self.stop.wait(15):
            try:
                if not self.state.data["backup"].get("weeks"):
                    try:
                        self.backup_schedules()
                    except Exception as err:
                        log.error("schedule backup failed, will retry: %s", err)
                now = datetime.now()
                for key in SCHEDULES:
                    self.schedule_state(key, now)
                self.holiday(now)
                self.check_overrides()
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
