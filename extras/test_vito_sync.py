"""Integration tests of the schedule helper sync with a simulated Home Assistant and a simulated controller.
Needs the splitter's environment (paho-mqtt, settings): run from the repository root
    PYTHONPATH=.:extras python -m unittest extras/test_vito_sync.py
"""
import os
import tempfile
import unittest
from datetime import datetime

import vito_extras as ex
import vito_logic as logic

DAY_HK1 = bytes.fromhex("20b8ffffffffffff")         # 04:00-23:00
EMPTY = bytes([0xFF] * 8)


class FakeHA:
    def __init__(self):
        self.helpers, self.calls = {}, []

    def call(self, msg):
        self.calls.append(msg)
        kind = msg["type"]
        if kind == "schedule/list":
            return list(self.helpers.values())
        if kind == "schedule/create":
            helper = {k: v for k, v in msg.items() if k != "type"}
            helper["id"] = "vito_" + str(len(self.helpers) + 1)
            self.helpers[helper["id"]] = helper
            return helper
        if kind == "schedule/update":
            helper = {k: v for k, v in msg.items() if k not in ("type", "schedule_id")}
            helper["id"] = msg["schedule_id"]
            self.helpers[helper["id"]] = helper
            return helper
        return {}

    def kinds(self):
        return [c["type"] for c in self.calls]


class FakeExtras(ex.Extras):
    """Extras with the Optolink access replaced by an in-memory controller."""

    def __init__(self):
        super().__init__()
        self.weeks = {key: bytearray(DAY_HK1 * 7) for key in ex.SCHEDULES}
        self.writes = []
        self.regs = {}                                  # single byte registers written by commands
        self.reg_writes = []
        self.poll()

    def poll(self):
        for key, week in self.weeks.items():
            self.values[f"{key}_zeitprogramm_roh_1"] = bytes(week[:48]).hex()
            self.values[f"{key}_zeitprogramm_roh_2"] = bytes(week[48:]).hex()

    def read_week(self, key):
        return bytes(self.weeks[key])

    def write(self, addr, data):
        for key, (base, _, _) in ex.SCHEDULES.items():
            if base <= addr < base + 56:
                self.weeks[key][addr - base:addr - base + len(data)] = data
                self.writes.append((key, (addr - base) // 8, bytes(data)))
                return
        self.reg_writes.append((addr, data))
        self.regs[addr] = data

    def read_hex(self, addr, length):
        for key, (base, _, _) in ex.SCHEDULES.items():
            if base <= addr < base + 56:
                return bytes(self.weeks[key][addr - base:addr - base + length])
        return bytes([self.regs.get(addr, 0)]) * length

    def forcepoll(self):
        pass


class ProgramSwitchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        ex.STATE_FILE = os.path.join(self.tmp.name, "state.json")
        self.x = FakeExtras()

    def tearDown(self):
        self.tmp.cleanup()

    def test_comfort_on_cancels_eco_and_switches_comfort_on(self):
        self.x.handle_command("hk2_komfortbetrieb/set", "ON")
        self.assertEqual(self.x.reg_writes, [(0x4331, 0), (0x4330, 1)])
        self.assertEqual(self.x.published["VitoExt/hk2_komfortbetrieb"], "ON")
        self.assertEqual(self.x.published["VitoExt/hk2_sparbetrieb"], "OFF")

    def test_eco_on_and_off(self):
        self.x.handle_command("hk1_sparbetrieb/set", "ON")
        self.assertEqual(self.x.reg_writes, [(0x3330, 0), (0x3331, 1)])
        self.x.reg_writes.clear()
        self.x.handle_command("hk1_sparbetrieb/set", "OFF")
        self.assertEqual(self.x.reg_writes, [(0x3331, 0)])

    def test_state_follows_the_polled_flags(self):
        self.x.values.update({"hk2_partybetrieb": "ON", "hk2_sparbetrieb": "OFF"})
        self.x.program_switches("hk2")
        self.assertEqual((self.x.published["VitoExt/hk2_komfortbetrieb"], self.x.published["VitoExt/hk2_sparbetrieb"]), ("ON", "OFF"))

    def test_a_shown_command_is_not_overridden_by_a_stale_poll_but_by_the_next_one(self):
        self.x.handle_command("hk2_komfortbetrieb/set", "ON")
        self.x.values.update({"hk2_partybetrieb": "OFF", "hk2_sparbetrieb": "OFF"})   # poll that ran before the controller set its flag
        self.x.program_switches("hk2")
        self.assertEqual(self.x.published["VitoExt/hk2_komfortbetrieb"], "ON")
        self.x.switch_hold["hk2"] = 0                                                 # hold expired, a later poll decides
        self.x.program_switches("hk2")
        self.assertEqual(self.x.published["VitoExt/hk2_komfortbetrieb"], "OFF")

    def test_preset_comfort_uses_the_command_register(self):
        self.x.set_preset("hk2", "comfort")
        self.assertEqual(self.x.reg_writes, [(0x4331, 0), (0x4330, 0), (0x4330, 1)])

    def test_writes_are_limited_to_the_whitelist(self):
        self.assertTrue(all(ex.Extras.write_allowed(a, 1) for a in (0x4330, 0x4331, 0x3330, 0x3331)))
        self.assertFalse(ex.Extras.write_allowed(0x4303, 1))          # the status flag is not a command


class BoostSwitchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        ex.STATE_FILE = os.path.join(self.tmp.name, "state.json")
        self.x = FakeExtras()
        self.original = bytes(self.x.weeks["warmwasser"])

    def tearDown(self):
        self.tmp.cleanup()

    def test_switch_on_starts_and_off_ends_the_boost(self):
        self.x.handle_command("warmwasser_zusatzaufheizung/set", "ON")
        self.assertEqual(self.x.override_kind("warmwasser"), "boost")
        self.assertEqual(self.x.published["VitoExt/warmwasser_zusatzaufheizung"], "ON")
        self.assertEqual(self.x.published["VitoExt/warmwasser_zeitprogramm_aktiv"], "OFF")
        self.x.handle_command("warmwasser_zusatzaufheizung/set", "OFF")
        self.assertIsNone(self.x.override_kind("warmwasser"))
        self.assertEqual(bytes(self.x.weeks["warmwasser"]), self.original)               # the time program is restored
        self.assertEqual(self.x.published["VitoExt/warmwasser_zusatzaufheizung"], "OFF")
        self.assertEqual(self.x.published["VitoExt/warmwasser_zeitprogramm_aktiv"], "ON")

    def test_switch_off_without_a_boost_writes_nothing(self):
        self.x.handle_command("zirkulation_zusatzlauf/set", "OFF")
        self.assertEqual(self.x.writes, [])
        self.assertEqual(self.x.published["VitoExt/zirkulation_zusatzlauf"], "OFF")

    def test_the_duration_is_kept_in_steps_of_ten_minutes(self):
        self.x.handle_command("zirkulation_zusatzlauf_dauer/set", "47")
        self.assertEqual(self.x.published["VitoExt/zirkulation_zusatzlauf_dauer"], "50")

    def test_permanent_operation_off_does_not_end_a_boost_and_boost_off_does_not_end_permanent(self):
        self.x.handle_command("warmwasser_zusatzaufheizung/set", "ON")
        self.x.handle_command("warmwasser_dauerbetrieb/set", "OFF")
        self.assertEqual(self.x.override_kind("warmwasser"), "boost")
        self.x.handle_command("warmwasser_zusatzaufheizung/set", "OFF")
        self.x.handle_command("warmwasser_dauerbetrieb/set", "ON")
        self.assertEqual(self.x.override_kind("warmwasser"), "permanent")
        self.x.handle_command("warmwasser_zusatzaufheizung/set", "OFF")
        self.assertEqual(self.x.override_kind("warmwasser"), "permanent")
        self.x.handle_command("warmwasser_dauerbetrieb/set", "OFF")
        self.assertIsNone(self.x.override_kind("warmwasser"))
        self.assertEqual(bytes(self.x.weeks["warmwasser"]), self.original)


class HolidayCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        ex.STATE_FILE = os.path.join(self.tmp.name, "state.json")
        self.x = FakeExtras()

    def tearDown(self):
        self.tmp.cleanup()

    def test_start_is_written_to_all_circuits_like_the_app(self):
        self.x.handle_command("urlaubsprogramm_beginn/set", "2026-10-16")
        raw = bytes.fromhex("2026101605235959")                     # as recorded from the app
        self.assertEqual(self.x.reg_writes, [(0x2309, raw), (0x3309, raw), (0x4309, raw)])
        self.assertEqual(self.x.published["VitoExt/urlaubsprogramm_beginn"], "2026-10-16")

    def test_end_before_the_start_is_refused_and_the_real_state_shown(self):
        self.x.values.update({"urlaubsprogramm_beginn": "Mo 19.10.2026 23:59:59", "urlaubsprogramm_ende": "Fr 20.11.2026 00:00:00"})
        with self.assertRaises(ValueError):
            self.x.handle_command("urlaubsprogramm_ende/set", "2026-10-18")
        self.assertEqual(self.x.reg_writes, [])
        self.assertEqual(self.x.published["VitoExt/urlaubsprogramm_ende"], "2026-11-20")

    def test_end_holiday_writes_the_unset_marker_to_all_circuits(self):
        self.x.handle_command("urlaubsprogramm_beenden/press", "PRESS")
        start, end = bytes.fromhex("1970010104235959"), bytes.fromhex("1970010104000000")
        self.assertEqual(self.x.reg_writes, [(0x2309, start), (0x2311, end), (0x3309, start), (0x3311, end), (0x4309, start), (0x4311, end)])
        self.assertEqual((self.x.published["VitoExt/urlaubsprogramm_beginn"], self.x.published["VitoExt/urlaubsprogramm_ende"]), ("None", "None"))

    def test_polled_dates_are_shown_after_the_hold(self):
        self.x.values.update({"urlaubsprogramm_beginn": "Mo 19.10.2026 23:59:59", "urlaubsprogramm_ende": "Fr 20.11.2026 00:00:00"})
        self.x.holiday(datetime(2026, 10, 17, 12))
        self.assertEqual((self.x.published["VitoExt/urlaubsprogramm_beginn"], self.x.published["VitoExt/urlaubsprogramm_ende"]), ("2026-10-19", "2026-11-20"))
        self.assertEqual(self.x.published["VitoExt/urlaubsprogramm"], "OFF")                  # not started yet
        self.x.holiday(datetime(2026, 10, 25, 12))
        self.assertEqual(self.x.published["VitoExt/urlaubsprogramm"], "ON")

    def test_only_the_holiday_registers_of_the_circuits_are_writable_with_8_bytes(self):
        self.assertTrue(all(ex.Extras.write_allowed(a, 8) for a in (0x2309, 0x2311, 0x3309, 0x3311, 0x4309, 0x4311)))
        self.assertFalse(ex.Extras.write_allowed(0x4309, 16))
        self.assertFalse(ex.Extras.write_allowed(0x4310, 8))


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        ex.STATE_FILE = os.path.join(self.tmp.name, "state.json")
        self.x = FakeExtras()
        self.ha = FakeHA()
        self.name = ex.SCHEDULE_HELPERS["hk1"][0]

    def tearDown(self):
        self.tmp.cleanup()

    def sync(self):
        helper = {h["name"]: h for h in self.ha.helpers.values()}.get(self.name)
        self.x.sync_hold.clear()
        self.x.sync_one(self.ha, "hk1", helper)
        return helper

    def helper(self):
        return {h["name"]: h for h in self.ha.helpers.values()}[self.name]

    def prime(self):
        self.sync()                                   # creates the helper and the baseline
        self.ha.calls.clear()

    def test_creates_helper_from_controller(self):
        self.sync()
        self.assertIn("schedule/create", self.ha.kinds())
        self.assertEqual(self.helper()["friday"], [{"from": "04:00:00", "to": "23:00:00"}])
        self.assertEqual(self.x.writes, [])

    def test_no_change_no_traffic(self):
        self.prime()
        self.sync()
        self.assertEqual(self.ha.kinds(), [])
        self.assertEqual(self.x.writes, [])

    def test_helper_edit_is_written_to_the_controller(self):
        self.prime()
        h = self.helper()
        h["tuesday"] = [{"from": "05:00:00", "to": "09:00:00"}, {"from": "17:00:00", "to": "22:00:00"}]
        self.sync()
        self.assertEqual([w[:2] for w in self.x.writes], [("hk1", 1)])                 # only Tuesday
        self.assertEqual(logic.week_to_slots(self.x.weeks["hk1"])[1], [(300, 540), (1020, 1320)])
        self.assertNotIn("schedule/update", self.ha.kinds())                          # nothing to snap
        self.assertGreater(self.x.sync_hold["hk1"], 0)

    def test_times_are_snapped_and_written_back(self):
        self.prime()
        self.helper()["monday"] = [{"from": "05:03:00", "to": "06:01:00"}]
        self.sync()
        self.assertEqual(logic.week_to_slots(self.x.weeks["hk1"])[0], [(300, 370)])
        self.assertEqual(self.helper()["monday"], [{"from": "05:00:00", "to": "06:10:00"}])

    def test_controller_change_is_mirrored_to_the_helper(self):
        self.prime()
        self.x.weeks["hk1"][16:24] = bytes.fromhex("30a8ffffffffffff")                 # Wednesday 06:00-21:00 at the controller
        self.x.poll()
        self.sync()
        self.assertEqual(self.helper()["wednesday"], [{"from": "06:00:00", "to": "21:00:00"}])
        self.assertEqual(self.x.writes, [])

    def test_conflict_controller_wins_and_user_is_notified(self):
        self.prime()
        self.helper()["monday"] = [{"from": "07:00:00", "to": "08:00:00"}]
        self.x.weeks["hk1"][0:8] = bytes.fromhex("30a8ffffffffffff")
        self.x.poll()
        self.sync()
        self.assertEqual(self.helper()["monday"], [{"from": "06:00:00", "to": "21:00:00"}])
        self.assertIn("call_service", self.ha.kinds())
        self.assertEqual(self.x.writes, [])

    def test_too_many_periods_are_rejected(self):
        self.prime()
        self.helper()["saturday"] = [{"from": f"{h:02d}:00:00", "to": f"{h:02d}:30:00"} for h in (1, 3, 5, 7, 9)]
        self.sync()
        self.assertEqual(self.x.writes, [])
        self.assertEqual(self.helper()["saturday"], [{"from": "04:00:00", "to": "23:00:00"}])     # reverted to the controller
        self.assertIn("call_service", self.ha.kinds())

    def test_active_boost_keeps_the_original_for_restore(self):
        self.prime()
        day = 4                                                                          # Friday is boosted at the controller
        original = bytes(self.x.weeks["hk1"][day * 8:day * 8 + 8])
        boosted = logic.encode_day([(240, 1380), (1400, 1430)])
        self.x.weeks["hk1"][day * 8:day * 8 + 8] = boosted
        self.x.state.data["overrides"]["hk1"] = {"kind": "boost", "day": day, "original_day": original.hex(), "until": 9e12}
        self.x.poll()
        self.sync()
        self.assertEqual(self.ha.kinds(), [])                                            # the effective program is unchanged
        h = self.helper()
        h["friday"] = [{"from": "06:00:00", "to": "20:00:00"}]
        h["thursday"] = [{"from": "07:00:00", "to": "08:00:00"}]
        self.sync()
        self.assertEqual([w[:2] for w in self.x.writes], [("hk1", 3)])                   # Thursday written, Friday not
        self.assertEqual(bytes(self.x.weeks["hk1"][day * 8:day * 8 + 8]), boosted)       # the boosted day is untouched
        self.assertEqual(logic.decode_day(bytes.fromhex(self.x.state.data["overrides"]["hk1"]["original_day"])), [(360, 1200)])


class HvacActionTests(unittest.TestCase):
    """The climate entities show what their own circuit does, not what the burner does."""

    def setUp(self):
        self.x = FakeExtras()

    def test_each_circuit_has_its_own_action(self):
        self.x.values.update({"hk1_betriebsart": "1", "hk2_betriebsart": "2", "hk1_pumpe": "OFF", "hk2_pumpe": "ON"})
        self.x.values["brennermodulation"] = "35"
        self.x.recompute("brennermodulation", 1e9)
        self.assertEqual(self.x.published["VitoExt/hk1_hvac_action"], "off")       # floor heating switched off, burner runs
        self.assertEqual(self.x.published["VitoExt/hk2_hvac_action"], "heating")
        self.x.values["brennermodulation"] = "0"
        self.x.recompute("brennermodulation", 1e9)
        self.assertEqual(self.x.published["VitoExt/hk2_hvac_action"], "idle")
        self.assertEqual(self.x.published["VitoExt/hk1_hvac_action"], "off")

    def test_pump_and_mode_changes_update_the_action(self):
        self.x.values.update({"brennermodulation": "20", "hk1_betriebsart": "2", "hk1_pumpe": "OFF"})
        self.x.recompute("hk1_pumpe", 1e9)
        self.assertEqual(self.x.published["VitoExt/hk1_hvac_action"], "idle")      # burner runs for DHW, the pump is off
        self.x.values["hk1_pumpe"] = "ON"
        self.x.recompute("hk1_pumpe", 1e9)
        self.assertEqual(self.x.published["VitoExt/hk1_hvac_action"], "heating")
        self.x.values["hk1_betriebsart"] = "0"
        self.x.recompute("hk1_betriebsart", 1e9)
        self.assertEqual(self.x.published["VitoExt/hk1_hvac_action"], "off")


class ProgramTextTests(unittest.TestCase):
    """"Aktives Programm" of DHW and circulation."""

    def setUp(self):
        self.x = FakeExtras()                                     # every program: 04:00-23:00

    def text(self, key, when):
        self.x.schedule_state(key, when)
        return self.x.published[f"VitoExt/{key}_programm"]

    def test_time_program(self):
        self.assertEqual(self.text("warmwasser", datetime(2026, 10, 12, 10, 0)), "Warmwasser bis 23:00")
        self.assertEqual(self.text("zirkulation", datetime(2026, 10, 12, 10, 0)), "Zirkulation bis 23:00")
        self.assertEqual(self.text("warmwasser", datetime(2026, 10, 12, 23, 30)), "Aus bis 04:00")
        self.assertEqual(self.text("zirkulation", datetime(2026, 10, 12, 3, 0)), "Aus bis 04:00")

    def test_boost_and_permanent_operation(self):
        until = datetime(2026, 10, 12, 15, 30)
        self.x.state.data["overrides"]["warmwasser"] = {"kind": "boost", "until": until.timestamp()}
        self.assertEqual(self.text("warmwasser", datetime(2026, 10, 12, 15, 0)), "Zusatzaufheizung bis 15:30")
        self.x.state.data["overrides"]["zirkulation"] = {"kind": "permanent"}
        self.assertEqual(self.text("zirkulation", datetime(2026, 10, 12, 15, 0)), "Dauerbetrieb")
        self.x.state.data["overrides"]["zirkulation"] = {"kind": "boost", "until": until.timestamp()}
        self.assertEqual(self.text("zirkulation", datetime(2026, 10, 12, 15, 0)), "Zusatzlauf bis 15:30")


if __name__ == "__main__":
    unittest.main()
