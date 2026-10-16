"""Read-only Optolink probe (VS2/300). Reads raw bytes only; never writes datapoints.
Talks to the serial port directly, so stop the splitter service first (sudo systemctl stop optolink-splitter).

Usage: optolink_probe.py ADDR:LEN [ADDR:LEN ...]       e.g. probe.py 0x00f8:8 0x0800:2
       optolink_probe.py --file addrs.txt              one ADDR:LEN per line, '#' comments allowed
       optolink_probe.py --scan START END STEP         read [START,END) in STEP-byte blocks, print only successful blocks
Run from the repository root with PYTHONPATH=. (needs the splitter's modules and settings_ini.py).
"""
import sys
import time

import serial

import optolinkvs2
from c_settings_adapter import settings

settings.show_opto_rx = False


def parse(spec):
    addr, ln = spec.split(":")
    return int(addr, 0), int(ln, 0)


def open_port():
    return serial.serial_for_url(
        settings.port_optolink, baudrate=4800, parity=serial.PARITY_EVEN,
        stopbits=serial.STOPBITS_TWO, bytesize=serial.EIGHTBITS, exclusive=True, timeout=0,
    )


def read(ser, addr, ln):
    """Read with one re-init on protocol-level failure (rc other than 1/3)."""
    for attempt in (1, 2):
        rc, _, data = optolinkvs2.read_datapoint_ext(addr, ln, ser)
        if rc in (0x01, 0x03):
            return rc, bytes(data)
        # timeout / CRC / framing error: reset the protocol and try once more
        ser.write(bytes([0x04]))
        time.sleep(0.5)
        if not optolinkvs2.init_vs2(ser):
            break
    return rc, bytes(data)


def main(argv):
    ser = open_port()
    try:
        if not optolinkvs2.init_vs2(ser):
            print("INIT FAILED")
            return 2
        if argv and argv[0] == "--scan":
            start, end, step = (int(x, 0) for x in argv[1:4])
            ok = err = other = 0
            for addr in range(start, end, step):
                rc, data = read(ser, addr, step)
                if rc == 0x01:
                    ok += 1
                    print(f"{addr:04X} {data.hex()}", flush=True)
                elif rc == 0x03:
                    err += 1
                else:
                    other += 1
                    print(f"{addr:04X} !rc={rc:#x}", flush=True)
                if (addr - start) % (step * 256) == 0:
                    print(f"# progress {addr:04X} ok={ok} err={err} other={other}", file=sys.stderr, flush=True)
            print(f"# done ok={ok} err={err} other={other}", flush=True)
            return 0
        specs = []
        if argv and argv[0] == "--file":
            for line in open(argv[1]):
                line = line.split("#")[0].strip()
                if line:
                    specs.append(parse(line))
        else:
            specs = [parse(a) for a in argv]
        for addr, ln in specs:
            rc, data = read(ser, addr, ln)
            print(f"{addr:04X} len={ln:<3d} rc={rc:<3d} data={data.hex()}")
            time.sleep(0.05)
    finally:
        try:
            ser.write(bytes([0x04]))  # EOT: reset protocol, same as the splitter does on exit
        except Exception:
            pass
        ser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
