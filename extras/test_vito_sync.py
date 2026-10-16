"""Integration tests of the schedule helper sync with a simulated Home Assistant and a simulated controller.
Needs the splitter's environment (paho-mqtt, settings): run from the repository root
    PYTHONPATH=.:extras python -m unittest extras/test_vito_sync.py
"""
import os
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
