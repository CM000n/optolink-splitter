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
                         ["standby", "reduced", "normal", "comfort", "external", "standby", "unknown", "unknown", "unknown"])

    def test_program_register(self):
        self.assertEqual(v.program_register_offset("normal", False), 0x306)
        self.assertEqual(v.program_register_offset("reduced", False), 0x307)
        self.assertEqual(v.program_register_offset("normal", True), 0x308)
        self.assertEqual(v.program_register_offset("standby", False), 0x306)


if __name__ == "__main__":
    unittest.main()
