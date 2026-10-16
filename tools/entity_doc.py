"""Generate docs/vscotho1-entities.md from homeassistant_poll_list.py and extras/vito_extras.py.

Usage (repository root, any Python with paho-mqtt importable; a stub is enough because nothing connects):
    PYTHONPATH=.:extras python tools/entity_doc.py > docs/vscotho1-entities.md

Per device: entity id, display name, category and source (splitter = poll list, extras = companion service).
Hidden data points (discovery False) are listed separately because they have no Home Assistant entity.
"""
import homeassistant_poll_list as pl
import vito_extras as ex

DEVICE_ORDER = ["main", "anlage", "kessel", "brenner", "warmwasser", "zirkulation", "solar", "heizkreis_1", "heizkreis_2"]
PREFIX = pl.poll_list.get("dp_prefix", "vito_")


def rows():
    meta = pl.poll_list["entity_meta"]
    out, hidden = [], []
    main_name = pl.poll_list["device"]["name"]
    for domain in pl.poll_list["domains"]:
        for item in domain["poll"]:
            dp = item[1]
            m = meta.get(dp, {})
            if m.get("discovery") is False:
                hidden.append((m.get("device", "main"), dp, m.get("name", dp)))
            else:
                out.append((m.get("device", "main"), domain["domain"], dp, m.get("name", dp), m.get("entity_category") or "", "splitter"))
        for item in domain["nopoll"]:
            dp = item["name"]
            m = meta.get(dp, {})
            out.append((m.get("device", "main"), domain["domain"], dp, m.get("name", dp), m.get("entity_category") or "", "splitter"))
    for domain, dp, cfg in ex.entity_defs():
        device = cfg["device"]["identifiers"][0].split(pl.MAIN + "_", 1)[-1] if cfg["device"]["identifiers"][0] != pl.MAIN else "main"
        out.append((device, domain, dp, cfg["name"], cfg.get("entity_category") or "", "extras"))
    return out, hidden, main_name


def main():
    entities, hidden, _ = rows()
    devices = pl.poll_list["devices"]
    titles = {"main": pl.poll_list["device"]["name"], **{key: dev["name"] for key, dev in devices.items()}}
    print("# Entities of the Vitotronic 200 (VScotHO1) integration\n")
    print("Generated from `homeassistant_poll_list.py` (source *splitter*) and `extras/vito_extras.py` (source *extras*) by `tools/entity_doc.py`.")
    print(f"{len(entities)} entities in {len({e[0] for e in entities})} devices. Entity ids are `<domain>.{PREFIX}<name>`; the display names are German like in")
    print("Home Assistant. Home Assistant sorts the entities of a device by category (controls, sensors, configuration, diagnostic) and then by name.\n")
    for key in DEVICE_ORDER:
        mine = sorted((e for e in entities if e[0] == key), key=lambda e: (e[4] == "diagnostic", e[4] == "config", e[1], e[3]))
        if not mine:
            continue
        print(f"## {titles[key]}\n")
        print("| Entity | Name | Category | Source |\n|---|---|---|---|")
        for _, domain, dp, name, category, source in mine:
            print(f"| `{domain}.{PREFIX}{dp}` | {name or '(device name)'} | {category or 'primary'} | {source} |")
        print()
    if hidden:
        print("## Data points without an entity\n")
        print("Published on MQTT (`<topic>/<name>`), consumed by `extras/vito_extras.py` or kept for diagnostics.\n")
        print("| Data point | Name |\n|---|---|")
        for _, dp, name in sorted(hidden, key=lambda h: h[1]):
            print(f"| `{dp}` | {name} |")


if __name__ == "__main__":
    main()
