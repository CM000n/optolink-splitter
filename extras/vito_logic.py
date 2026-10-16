"""Pure helper functions of vito_extras.py (no MQTT, no I/O) so that they can be unit-tested.

Time program format of the Vitotronic: 7 days (Monday first) x 8 byte = 4 pairs (on, off) per day.
A byte is hour * 8 + minute / 10, 24:00 is 0xC0, 0xFF marks an unused entry.
"""
from datetime import datetime

MINUTES_PER_DAY = 1440
UNUSED = 0xFF


# --------------------------------------------------------------------------------------------------------------
# time programs
# --------------------------------------------------------------------------------------------------------------
def byte_to_minutes(value):
    return (value >> 3) * 60 + (value & 7) * 10


def minutes_to_byte(minutes):
    return (minutes // 60) * 8 + (minutes % 60) // 10


def decode_day(day):
    """8 bytes -> sorted list of (start_min, end_min); unused or invalid pairs are skipped."""
    slots = []
    for i in range(0, 8, 2):
        on, off = day[i], day[i + 1]
        if on == UNUSED or off == UNUSED:
            continue
        start, end = byte_to_minutes(on), byte_to_minutes(off)
        if end > start:
            slots.append((start, end))
    return sorted(slots)


def encode_day(slots):
    """list of (start_min, end_min) -> 8 bytes. Raises ValueError for more than 4 slots."""
    if len(slots) > 4:
        raise ValueError("more than 4 switching periods per day")
    out = bytearray([UNUSED] * 8)
    for i, (start, end) in enumerate(sorted(slots)):
        out[2 * i] = minutes_to_byte(start)
        out[2 * i + 1] = minutes_to_byte(end)
    return bytes(out)


def merge_slots(slots):
    """Merge overlapping or touching slots."""
    merged = []
    for start, end in sorted(slots):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def add_boost(day, now_minutes, duration_minutes):
    """Day bytes with an additional slot [now, now + duration] (rounded to 10 min, capped at 24:00).
    Returns (new_day_bytes, end_minute_of_boost)."""
    start = (now_minutes // 10) * 10
    end = min(-(-(now_minutes + duration_minutes) // 10) * 10, MINUTES_PER_DAY)
    if end <= start:
        raise ValueError("boost would end before it starts (too close to midnight)")
    return encode_day(merge_slots(decode_day(day) + [(start, end)])), end


def permanent_day():
    """00:00 - 24:00."""
    return encode_day([(0, MINUTES_PER_DAY)])


def is_active(week, when):
    """True if 'when' lies inside a switching period of the weekly program (56 bytes, Monday first)."""
    if len(week) < 56:
        week = bytes(week) + bytes([UNUSED] * (56 - len(week)))
    day = week[when.weekday() * 8: when.weekday() * 8 + 8]
    minute = when.hour * 60 + when.minute
    return any(start <= minute < end for start, end in decode_day(day))


def format_slots(day):
    return [f"{s // 60:02d}:{s % 60:02d}-{e // 60:02d}:{e % 60:02d}" for s, e in decode_day(day)]


# --------------------------------------------------------------------------------------------------------------
# heating curve (same formula the ViCare integration used)
# --------------------------------------------------------------------------------------------------------------
def heating_curve_target(outside, room_setpoint, slope, level):
    """Flow temperature set point of the Viessmann heating curve (condensing boiler, no limits applied)."""
    if None in (outside, room_setpoint, slope, level):
        return None
    d = outside - room_setpoint
    return round(room_setpoint + level - slope * d * (1.4347 + 0.021 * d + 0.0002479 * d * d), 1)


# --------------------------------------------------------------------------------------------------------------
# misc
# --------------------------------------------------------------------------------------------------------------
def parse_vdatetime(text):
    """'Fr 16.10.2026 09:52:11' -> datetime; None for the unset marker (1970) or garbage."""
    try:
        value = datetime.strptime(text.strip()[3:], "%d.%m.%Y %H:%M:%S")
    except (ValueError, AttributeError):
        return None
    return None if value.year <= 1970 else value


PROGRAMS = {0: "standby", 1: "reduced", 2: "normal", 3: "normal", 5: "standby"}   # 3 = permanently normal, comfort is the party flag


def program_name(code):
    """Active program of a circuit (byte 1 of the status block 0x?500) -> name; 0 and 5 are 'standby' for the API."""
    try:
        return PROGRAMS.get(int(float(code)), "unknown")
    except (TypeError, ValueError):
        return str(code) if code in PROGRAMS.values() else "unknown"


def preset_from(program, party, eco):
    """Home Assistant climate preset from the controller state."""
    if party:
        return "comfort"
    if eco:
        return "eco"
    return {"normal": "home", "reduced": "sleep"}.get(program, "none")


def program_register_offset(program, party):
    """Offset of the set point register that belongs to the active program (0x306 normal, 0x307 reduced, 0x308 comfort)."""
    if party or program == "comfort":
        return 0x308
    if program == "reduced":
        return 0x307
    return 0x306


# --------------------------------------------------------------------------------------------------------------
# fault history: 10 entries x 9 byte at 0x7507 (code + 8 byte BCD date yyyy mm dd weekday hh mm ss)
# --------------------------------------------------------------------------------------------------------------
def decode_fault(entry):
    """9 bytes -> (code, datetime) or None for an empty / invalid entry."""
    if len(entry) < 9 or entry[0] in (0x00, 0xFF):
        return None
    digits = entry[1:9].hex()
    try:
        when = datetime(int(digits[0:4]), int(digits[4:6]), int(digits[6:8]), int(digits[10:12]), int(digits[12:14]), int(digits[14:16]))
    except ValueError:
        return None
    return entry[0], when


# --------------------------------------------------------------------------------------------------------------
# Home Assistant schedule helper <-> controller time program
# --------------------------------------------------------------------------------------------------------------
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _hms_to_minutes(text):
    h, m, *_ = [int(x) for x in str(text).split(":")]
    return h * 60 + m


def helper_to_slots(config):
    """HA schedule helper config -> 7 lists (Monday first) of (start_min, end_min), snapped to the controller's 10 minute
    raster (start rounded down, end rounded up) and merged. 24:00:00 is accepted as end of the day."""
    week = []
    for day in WEEKDAYS:
        slots = []
        for rng in config.get(day) or []:
            start = (_hms_to_minutes(rng["from"]) // 10) * 10
            end = min(-(-_hms_to_minutes(rng["to"]) // 10) * 10, MINUTES_PER_DAY)
            if end > start:
                slots.append((start, end))
        week.append(merge_slots(slots))
    return week


def slots_to_helper(week_slots):
    """7 lists of (start_min, end_min) -> the weekday part of an HA schedule helper config."""
    def hms(minutes):
        return "24:00:00" if minutes >= MINUTES_PER_DAY else f"{minutes // 60:02d}:{minutes % 60:02d}:00"
    return {day: [{"from": hms(a), "to": hms(b)} for a, b in slots] for day, slots in zip(WEEKDAYS, week_slots)}


def week_to_slots(week):
    """56 bytes (Monday first) -> 7 normalised slot lists."""
    week = bytes(week) + bytes([UNUSED] * max(0, 56 - len(week)))
    return [merge_slots(decode_day(week[d * 8:d * 8 + 8])) for d in range(7)]


def slots_to_week(week_slots):
    """7 slot lists -> 56 bytes; ValueError when a day has more than 4 periods."""
    return b"".join(encode_day(day) for day in week_slots)


def sync_decision(baseline, helper, device):
    """Three way decision between the last synchronised state, the HA helper and the controller (all slot lists).
    Returns 'none', 'to_device', 'to_helper' or 'conflict' (the controller wins in a conflict)."""
    if helper == device:
        return "none"
    if baseline is None:
        return "to_helper"
    helper_changed, device_changed = helper != baseline, device != baseline
    if helper_changed and not device_changed:
        return "to_device"
    if device_changed and not helper_changed:
        return "to_helper"
    return "conflict"
