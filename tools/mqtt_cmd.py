"""Send commands to the running optolink-splitter via MQTT (<topic>/cmnd) and print the answers (<topic>/resp).

Usage (from the repository root, with the splitter's virtual environment):
    PYTHONPATH=. python tools/mqtt_cmd.py "read;0x0800;2;0.1;true" "read;0x3306;1;1"
    PYTHONPATH=. python tools/mqtt_cmd.py --listen 30            # print everything published below <topic> for 30 s

Broker and credentials are taken from settings_ini.py and are never printed.
Commands are sent one after the other; each one waits up to 4 s for an answer for the same address.
write/writeraw commands are sent as given, so use them deliberately.
"""
import sys
import threading
import time

import paho.mqtt.client as paho

from c_settings_adapter import settings


def connect():
    host, port = settings.mqtt_broker.split(":")
    client = paho.Client(paho.CallbackAPIVersion.VERSION2, "optolink_mqtt_cmd_" + str(int(time.time())))
    if settings.mqtt_user and str(settings.mqtt_user).lower() != "none":
        user, password = str(settings.mqtt_user).split(":", 1)
        client.username_pw_set(user, password)
    client.connect(host, int(port), 30)
    return client


def listen(seconds):
    client = connect()
    seen = {}

    def on_message(_c, _u, msg):
        seen[msg.topic] = msg.payload.decode(errors="replace")[:100]

    client.on_message = on_message
    client.subscribe(settings.mqtt_topic + "/#")
    client.loop_start()
    time.sleep(seconds)
    client.loop_stop()
    for topic in sorted(seen):
        if "/viconn/" not in topic:
            print(f"{topic:60s} {seen[topic]}")


def run(commands):
    client = connect()
    answers = []
    event = threading.Event()

    def on_message(_c, _u, msg):
        answers.append(msg.payload.decode(errors="replace"))
        event.set()

    client.on_message = on_message
    client.subscribe(settings.mqtt_respond)
    client.loop_start()
    time.sleep(0.5)
    for cmd in commands:
        answers.clear()
        event.clear()
        client.publish(settings.mqtt_listen, cmd)
        event.wait(4)
        print(f"{cmd:48s} -> {answers[0] if answers else '(no answer)'}")
        time.sleep(0.2)
    client.loop_stop()


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--listen":
        listen(int(sys.argv[2]))
    elif len(sys.argv) > 1:
        run(sys.argv[1:])
    else:
        print(__doc__)
