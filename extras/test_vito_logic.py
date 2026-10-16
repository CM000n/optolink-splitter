import unittest
from datetime import datetime

import vito_logic as v

# real data of the reference installation (see docs/vscotho1.md)
HK1_WEEK = bytes.fromhex("20b8ffffffffffff" * 7)                      # 04:00-23:00 every day
HK2_WEEK = bytes.fromhex("ffff30a8ffffffff" * 7)                      # 06:00-21:00 (second pair)
CIRC_DAY = bytes.fromhex("2848606890a8ffff")                          # 05-09, 12-13, 18-21


class Slots(unittest.TestCase):
    def test_decode(self):
        self.assertEqual(v.decode_day(CIRC_DAY), [(300, 540), (720, 780), (1080, 1260)])
        self.assertEqual(v.decode_day(HK2_WEEK[:8]), [(360, 1260)])

    def test_roundtrip(self):
        for day in (CIRC_DAY, HK1_WEEK[:8], HK2_WEEK[:8].replace(b"\xff\xff\x30\xa8", b"\x30\xa8\xff\xff")):
            self.assertEqual(v.encode_day(v.decode_day(day)), day)

    def test_24h_byte(self):
        self.assertEqual(v.permanent_day(), bytes.fromhex("00c0ffffffffffff"))
        self.assertEqual(v.byte_to_minutes(0xC0), 1440)

    def test_format(self):
        self.assertEqual(v.format_slots(CIRC_DAY), ["05:00-09:00", "12:00-13:00", "18:00-21:00"])


class Boost(unittest.TestCase):
    def test_boost_inside_existing_slot_is_a_noop(self):
        day = v.encode_day([(360, 1260)])
        new, end = v.add_boost(day, 8 * 60 + 7, 30)
        self.assertEqual(new, day)
        self.assertEqual(end, 8 * 60 + 40)

    def test_boost_outside_adds_slot(self):
        day = v.encode_day([(360, 1260)])
        new, end = v.add_boost(day, 22 * 60 + 3, 60)
        self.assertEqual(v.decode_day(new), [(360, 1260), (1320, 1390)])
        self.assertEqual(end, 1390)

    def test_boost_touching_slot_is_merged(self):
        day = v.encode_day([(360, 1260)])
        new, _ = v.add_boost(day, 21 * 60, 30)
        self.assertEqual(v.decode_day(new), [(360, 1290)])

    def test_boost_is_capped_at_midnight(self):
        day = v.encode_day([(360, 600)])
        new, end = v.add_boost(day, 23 * 60 + 50, 120)
        self.assertEqual(end, 1440)
        self.assertEqual(v.decode_day(new)[-1], (1430, 1440))

    def test_too_many_slots(self):
        day = v.encode_day([(60, 120), (180, 240), (300, 360), (420, 480)])
        with self.assertRaises(ValueError):
            v.add_boost(day, 12 * 60, 30)


class Active(unittest.TestCase):
    def test_is_active(self):
        week = HK2_WEEK
        self.assertTrue(v.is_active(week, datetime(2026, 10, 16, 9, 0)))       # Friday
        self.assertFalse(v.is_active(week, datetime(2026, 10, 16, 21, 0)))
        self.assertFalse(v.is_active(week, datetime(2026, 10, 16, 5, 59)))

    def test_short_week_is_padded(self):
        self.assertTrue(v.is_active(HK1_WEEK[:55], datetime(2026, 10, 18, 12, 0)))   # Sunday, last byte missing


class Curve(unittest.TestCase):
    def test_matches_api_values(self):
        # values recorded from the ViCare integration at outside 9.5 deg C (room set point 20)
        self.assertAlmostEqual(v.heating_curve_target(9.5, 20, 0.8, 1), 31.4, places=1)
        self.assertAlmostEqual(v.heating_curve_target(9.5, 20, 1.2, 1), 36.6, places=1)

    def test_missing_input(self):
        self.assertIsNone(v.heating_curve_target(None, 20, 1.2, 1))


class Faults(unittest.TestCase):
    def test_decode_fault(self):
        self.assertEqual(v.decode_fault(bytes.fromhex("c22025062907071038")), (0xC2, datetime(2025, 6, 29, 7, 10, 38)))
        self.assertEqual(v.decode_fault(bytes.fromhex("9a2023041405100626")), (0x9A, datetime(2023, 4, 14, 10, 6, 26)))

    def test_empty_entries(self):
        self.assertIsNone(v.decode_fault(bytes.fromhex("00" + "ff" * 8)))
        self.assertIsNone(v.decode_fault(bytes.fromhex("ff" + "ff" * 8)))
        self.assertIsNone(v.decode_fault(bytes.fromhex("c22025133207071038")))     # month 13 / day 32


class HelperSync(unittest.TestCase):
    CIRC = {"monday": [{"from": "05:00:00", "to": "09:00:00"}, {"from": "12:00:00", "to": "13:00:00"}, {"from": "18:00:00", "to": "21:00:00"}],
            "sunday": [{"from": "00:00:00", "to": "24:00:00"}]}

    def test_helper_roundtrip(self):
        slots = v.helper_to_slots(self.CIRC)
        self.assertEqual(slots[0], [(300, 540), (720, 780), (1080, 1260)])
        self.assertEqual(slots[6], [(0, 1440)])
        self.assertEqual(slots[1], [])
        back = v.slots_to_helper(slots)
        self.assertEqual(back["monday"], self.CIRC["monday"])
        self.assertEqual(back["sunday"], [{"from": "00:00:00", "to": "24:00:00"}])
        self.assertEqual(back["tuesday"], [])

    def test_snapping_and_merge(self):
        cfg = {"monday": [{"from": "05:03:00", "to": "06:01:00"}, {"from": "06:05:00", "to": "07:00:00"}]}
        self.assertEqual(v.helper_to_slots(cfg)[0], [(300, 420)])           # 05:00-06:10 and 06:00-07:00 touch -> merged

    def test_week_conversion(self):
        week = bytes.fromhex("ffff30a8ffffffff" * 7)
        slots = v.week_to_slots(week)
        self.assertEqual(slots[2], [(360, 1260)])
        self.assertEqual(v.week_to_slots(v.slots_to_week(slots)), slots)
        self.assertEqual(len(v.slots_to_week(slots)), 56)

    def test_too_many_periods(self):
        day = [(60, 120), (180, 240), (300, 360), (420, 480), (540, 600)]
        with self.assertRaises(ValueError):
            v.slots_to_week([day] + [[]] * 6)

    def test_short_device_week(self):
        self.assertEqual(len(v.week_to_slots(bytes.fromhex("20b8ffffffffffff") * 6 + bytes(7))), 7)

    def test_decision(self):
        a, b, c = [[(60, 120)]] * 7, [[(60, 180)]] * 7, [[(0, 60)]] * 7
        self.assertEqual(v.sync_decision(a, a, a), "none")
        self.assertEqual(v.sync_decision(a, b, a), "to_device")
        self.assertEqual(v.sync_decision(a, a, b), "to_helper")
        self.assertEqual(v.sync_decision(a, b, c), "conflict")
        self.assertEqual(v.sync_decision(a, b, b), "none")
        self.assertEqual(v.sync_decision(None, b, a), "to_helper")


class Misc(unittest.TestCase):
    def test_vdatetime(self):
        self.assertEqual(v.parse_vdatetime("Fr 16.10.2026 09:52:11"), datetime(2026, 10, 16, 9, 52, 11))
        self.assertIsNone(v.parse_vdatetime("Do 01.01.1970 00:00:00"))
        self.assertIsNone(v.parse_vdatetime("garbage"))

    def test_preset(self):
        self.assertEqual(v.preset_from("normal", False, False), "home")
        self.assertEqual(v.preset_from("reduced", False, False), "sleep")
        self.assertEqual(v.preset_from("normal", True, False), "comfort")
        self.assertEqual(v.preset_from("normal", False, True), "eco")
        self.assertEqual(v.preset_from("standby", False, False), "none")

    def test_program_name(self):
        self.assertEqual([v.program_name(c) for c in ("0", "1", "2", "3", "4", "5", "9", "x", None)],
                         ["standby", "reduced", "normal", "normal", "unknown", "standby", "unknown", "unknown", "unknown"])

    def test_program_register(self):
        self.assertEqual(v.program_register_offset("normal", False), 0x306)
        self.assertEqual(v.program_register_offset("reduced", False), 0x307)
        self.assertEqual(v.program_register_offset("normal", True), 0x308)
        self.assertEqual(v.program_register_offset("standby", False), 0x306)


class HeizmodusTests(unittest.TestCase):
    WEEK = [[(360, 1260)]] * 7                      # every day 06:00-21:00

    def test_next_switch_inside_and_outside_a_period(self):
        mon = datetime(2026, 10, 12)                # a Monday
        self.assertEqual(v.next_switch(self.WEEK, mon.replace(hour=20, minute=12)), mon.replace(hour=21))
        self.assertEqual(v.next_switch(self.WEEK, mon.replace(hour=21, minute=45)), datetime(2026, 10, 13, 6))
        self.assertEqual(v.next_switch(self.WEEK, mon.replace(hour=21)), datetime(2026, 10, 13, 6))
        self.assertEqual(v.next_switch(self.WEEK, mon.replace(hour=5, minute=59, second=30)), mon.replace(hour=6))

    def test_next_switch_wraps_around_the_week_and_ignores_midnight(self):
        week = [[] for _ in range(7)]
        week[2] = [(1200, 1440)]                    # Wed 20:00-24:00
        week[3] = [(0, 120)]                        # Thu 00:00-02:00 continues the evening
        wed = datetime(2026, 10, 14)
        self.assertEqual(v.next_switch(week, wed.replace(hour=22)), datetime(2026, 10, 15, 2))
        self.assertEqual(v.next_switch(week, wed.replace(hour=2)), wed.replace(hour=20))
        self.assertEqual(v.next_switch(week, datetime(2026, 10, 15, 3)), datetime(2026, 10, 21, 20))   # next Wednesday

    def test_next_switch_without_changes(self):
        self.assertIsNone(v.next_switch([[] for _ in range(7)], datetime(2026, 10, 12, 12)))
        self.assertIsNone(v.next_switch([[(0, 1440)]] * 7, datetime(2026, 10, 12, 12)))

    def test_heizmodus_text_like_the_app(self):
        until = datetime(2026, 10, 12, 21)
        self.assertEqual(v.heizmodus_text(0, 0, False, False, None), "Aus")
        self.assertEqual(v.heizmodus_text("1", "0", False, False, None), "Aus")
        self.assertEqual(v.heizmodus_text(4, 3, False, False, until), "Normal")
        self.assertEqual(v.heizmodus_text(3, 1, False, False, until), "Reduziert")
        self.assertEqual(v.heizmodus_text(2, 2, False, False, until), "Normal bis 21:00")
        self.assertEqual(v.heizmodus_text(2, 1, False, False, until), "Reduziert bis 21:00")
        self.assertEqual(v.heizmodus_text(2, 1, False, False, None), "Reduziert")
        self.assertEqual(v.heizmodus_text(2, 2, True, False, until), "Komfortbetrieb")
        self.assertEqual(v.heizmodus_text(4, 3, True, False, until), "Komfortbetrieb")
        self.assertEqual(v.heizmodus_text(2, 1, False, True, until), "Sparbetrieb")
        self.assertEqual(v.heizmodus_text(1, 0, True, False, None), "Aus")         # off wins over comfort
        self.assertIsNone(v.heizmodus_text(None, 2, False, False, until))
        self.assertIsNone(v.heizmodus_text(2, 9, False, False, until))

    def test_zeitprogramm_aktiv(self):
        self.assertTrue(v.zeitprogramm_aktiv(2, False, False))
        self.assertTrue(v.zeitprogramm_aktiv("2", False, False))
        self.assertFalse(v.zeitprogramm_aktiv(2, True, False))      # comfort pauses it
        self.assertFalse(v.zeitprogramm_aktiv(2, False, True))      # eco pauses it
        self.assertFalse(v.zeitprogramm_aktiv(3, False, False))     # permanently reduced
        self.assertFalse(v.zeitprogramm_aktiv(4, False, False))     # permanently normal
        self.assertFalse(v.zeitprogramm_aktiv(0, False, False))     # off
        self.assertIsNone(v.zeitprogramm_aktiv(None, False, False))


if __name__ == "__main__":
    unittest.main()
