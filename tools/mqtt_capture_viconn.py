"""Capture the Vitoconnect's own Optolink requests as published by the splitter (Vito/viconn/<addr>/<msgid>).
Usage: mqtt_capture_viconn.py SECONDS OUTFILE   (credentials come from settings_ini.py, never printed)
Output: one JSON line per distinct (addr, msgid, payload) with first/last seen and count."""
import json, sys, time
import paho.mqtt.client as paho
from c_settings_adapter import settings

secs = int(sys.argv[1]); out = sys.argv[2]
host, port = settings.mqtt_broker.split(":")
c = paho.Client(paho.CallbackAPIVersion.VERSION2, "capture_viconn")
u, p = str(settings.mqtt_user).split(":", 1)
c.username_pw_set(u, p)
seen = {}
t0 = time.time()
def on_msg(cl, ud, m):
    parts = m.topic.split("/")          # Vito / viconn / ADDR / MSGID
    if len(parts) < 4:
        return
    key = (parts[2], parts[3], m.payload.decode(errors="replace"))
    now = time.time() - t0
    e = seen.setdefault(key, {"first": round(now, 1), "n": 0})
    e["n"] += 1; e["last"] = round(now, 1)
c.on_message = on_msg
c.connect(host, int(port), 30)
c.subscribe(settings.mqtt_topic + "/viconn/#")
c.loop_start(); time.sleep(secs); c.loop_stop()
with open(out, "w") as f:
    for (addr, msgid, payload), e in sorted(seen.items()):
        f.write(json.dumps({"addr": addr, "msgid": msgid, "payload": payload[:400], **e}) + "\n")
print(len(seen), "distinct viconn messages captured in", secs, "s")
