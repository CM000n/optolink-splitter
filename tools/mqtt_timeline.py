"""Timeline of what happens on the bus while you operate the ViCare app (or anything else). Read-only.

Usage (repository root, with the splitter's virtual environment):
    PYTHONPATH=. python tools/mqtt_timeline.py SECONDS OUTFILE INTERVAL "read;0x4301;1;1" "read;0x4500;22;raw" ...

* logs every change of a Vitoconnect / controller message (<topic>/viconn/<addr>/<msgid>) and every Vitoconnect write
  with a time stamp; this shows which register the app (via the cloud and the Vitoconnect) really writes
* reads the given datapoints every INTERVAL seconds through <topic>/cmnd and logs every change

Needs viconn_to_mqtt = True. Credentials come from settings_ini.py and are never printed.
"""
import json
import sys
import threading
import time
from datetime import datetime

import paho.mqtt.client as paho

from c_settings_adapter import settings


def stamp():
    return datetime.now().strftime("%H:%M:%S")


def main():
    seconds, outfile, interval, commands = int(sys.argv[1]), sys.argv[2], float(sys.argv[3]), sys.argv[4:]
    host, port = settings.mqtt_broker.split(":")
    client = paho.Client(paho.CallbackAPIVersion.VERSION2, "optolink_timeline")
    if settings.mqtt_user and str(settings.mqtt_user).lower() != "none":
        user, password = str(settings.mqtt_user).split(":", 1)
        client.username_pw_set(user, password)
    out = open(outfile, "a", buffering=1)
    last_viconn, answers, event = {}, [], threading.Event()

    def on_message(_c, _u, msg):
        payload = msg.payload.decode(errors="replace")
        if msg.topic == settings.mqtt_respond:
            answers.append(payload)
            event.set()
            return
        parts = msg.topic.split("/")  # <topic> / viconn / ADDR / MSGID
        if len(parts) < 4 or parts[1] != "viconn":
            return
        key = (parts[2], parts[3])
        is_write = "WRITE" in payload.upper()
        if last_viconn.get(key) != payload or is_write:
            last_viconn[key] = payload
            print(f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]} VICONN {parts[2]} {parts[3]} {payload[:300]}"
                  + ("   <== WRITE" if is_write else ""), file=out)

    client.on_message = on_message
    client.connect(host, int(port), 30)
    client.subscribe([(settings.mqtt_topic + "/viconn/#", 0), (settings.mqtt_respond, 0)])
    client.loop_start()
    print(f"{stamp()} START {seconds}s every {interval}s: {commands}", file=out)
    last_poll, end = {}, time.time() + seconds
    while time.time() < end:
        cycle = time.time()
        for cmd in commands:
            answers.clear()
            event.clear()
            client.publish(settings.mqtt_listen, cmd)
            addr = cmd.split(";")[1].strip().lower().replace("0x", "").lstrip("0")  # ignore answers to other clients' commands
            value, deadline = "(no answer)", time.time() + 4
            while time.time() < deadline:
                event.wait(max(0.0, deadline - time.time()))
                match = [a for a in list(answers) if addr in a.lower().replace("0x", "")]
                if match:
                    value = match[0]
                    break
                event.clear()
            if last_poll.get(cmd) != value:
                last_poll[cmd] = value
                print(f"{stamp()} POLL {cmd} -> {value}", file=out)
            time.sleep(0.1)
        time.sleep(max(0.0, interval - (time.time() - cycle)))
    print(f"{stamp()} END", file=out)
    client.loop_stop()


if __name__ == "__main__":
    if len(sys.argv) < 5:
        print(__doc__)
    else:
        main()
