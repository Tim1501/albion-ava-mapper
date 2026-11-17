# Albion Ava Mapper (c) 2026 ChanaMasala. All rights reserved. Free for personal use only.
# Copying, redistributing, reusing in other projects, or using with AI to train on, copy or rebuild
# this code needs written permission from the creator (Discord: @ChanaMasala). See LICENSE.
"""Builds the Roads of Avalon zone cards from Albion's own game files (ao-bin-dumps).

For every Avalonian zone it works out, straight from the game data:
  - name, tier and connection type          (cluster/world.xml)
  - chests: green, blue (small/big), gold (small/big)
        counted from the chest spawn points inside each camp the zone's layout places,
        for the zone's own tier                  (cluster/TNL-*.cluster.xml + templates)
  - gathering spots: type and size (small/big)  (layout resource patches + world minimap markers)
  - dungeon entrances: solo / group / elite      (world minimap markers)
  - resource nodes by type and tier            (world.xml distribution)

Writes data/game/zones.json and data/game/meta.json.
Run by hand:  python avadata.py [folder-with-already-downloaded-files]
"""
import concurrent.futures as cf
import datetime
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.request
import xml.etree.ElementTree as ET

RAW = "https://raw.githubusercontent.com/ao-data/ao-bin-dumps/master/"
TREE_API = "https://api.github.com/repos/ao-data/ao-bin-dumps/git/trees/master?recursive=1"
COMMITS_API = "https://api.github.com/repos/ao-data/ao-bin-dumps/commits?path=cluster/world.xml&per_page=1"
UA = {"User-Agent": "AlbionAvaMapper/1.0"}
TIER_RE = re.compile(r"_T(\d)_")
CHEST_RE = re.compile(r"LOOTCHEST_(SMALL|MEDIUM)_AVALON_ROAD(?:_(VETERAN|ELITE))?_T(\d)$", re.I)
RES_RE = re.compile(r"^(S|M)_ROADS_RES_([A-Za-z]+?)_\d+$")
RES_PAIRS = {"OreRock": ("Ore", "Stone"), "WoodFiber": ("Wood", "Fiber"), "FiberHide": ("Fiber", "Hide"),
             "HideOre": ("Hide", "Ore"), "RockWood": ("Stone", "Wood")}
GATHER_TYPES = ("Ore", "Wood", "Fiber", "Hide", "Stone")

# Zone type -> what the zone connects to. Labels can be renamed in the app later.
CONNECTIONS = {
    "TUNNEL_ROYAL": ("royal", "Royal"),
    "TUNNEL_ROYAL_RED": ("royal", "Royal (red)"),
    "TUNNEL_BLACK_LOW": ("black", "Black zone"),
    "TUNNEL_BLACK_MEDIUM": ("black", "Black zone"),
    "TUNNEL_BLACK_HIGH": ("black", "Black zone"),
    "TUNNEL_HIDEOUT": ("hideout", "Hideout"),
    "TUNNEL_HIDEOUT_DEEP": ("deep", "Deeper (hideout)"),
    "TUNNEL_DEEP": ("deep", "Deeper"),
    "TUNNEL_DEEP_RAID": ("deep", "Deeper (raid)"),
    "TUNNEL_LOW": ("roads", "Roads"),
    "TUNNEL_MEDIUM": ("roads", "Roads"),
    "TUNNEL_HIGH": ("roads", "Roads"),
}


# ------------------------------------------------------------------ fetch --
def get(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def latest_version():
    try:
        c = json.loads(get(COMMITS_API, 15))[0]
        return c["sha"][:10], c["commit"]["committer"]["date"]
    except Exception:  # noqa: BLE001
        return None, None


def download(dest, progress):
    """Fetch world.xml, the Avalon layouts and the camp/resource templates into dest."""
    os.makedirs(os.path.join(dest, "layouts"), exist_ok=True)
    os.makedirs(os.path.join(dest, "templates"), exist_ok=True)
    progress("Downloading the world list (13 MB)", 0.05)
    with open(os.path.join(dest, "world.xml"), "wb") as f:
        f.write(get(RAW + "cluster/world.xml", 180))
    files = sorted({c.get("file") for c in world_clusters(os.path.join(dest, "world.xml"))})

    def fetch_layout(name):
        p = os.path.join(dest, "layouts", name)
        if not os.path.exists(p):
            with open(p, "wb") as f:
                f.write(get(RAW + "cluster/" + name))
    progress(f"Downloading {len(files)} zone layouts", 0.35)
    with cf.ThreadPoolExecutor(8) as ex:
        list(ex.map(fetch_layout, files))

    refs = set()
    for name in files:
        for ti in ET.parse(os.path.join(dest, "layouts", name)).getroot().iter("templateinstance"):
            if "_PVE_" in ti.get("ref") or "_RES_" in ti.get("ref"):
                refs.add(ti.get("ref"))
    tree = json.loads(get(TREE_API, 60))["tree"]
    where = {}
    for x in tree:
        p = x["path"]
        if p.startswith("templates/") and p.endswith(".template.xml"):
            ref, folder = os.path.basename(p)[:-13], p.split("/")[1]
            if ref not in where or folder == "NONE":
                where[ref] = folder

    def fetch_template(ref):
        p = os.path.join(dest, "templates", ref + ".xml")
        if ref in where and not os.path.exists(p):
            with open(p, "wb") as f:
                f.write(get(f"{RAW}templates/{where[ref]}/{ref}.template.xml"))
    progress(f"Downloading {len(refs)} camp templates", 0.65)
    with cf.ThreadPoolExecutor(8) as ex:
        list(ex.map(fetch_template, sorted(refs)))


# ------------------------------------------------------------------ build --
def world_clusters(path):
    return [c for c in ET.parse(path).getroot().iter("cluster")
            if c.get("id", "").startswith("TNL-") and c.get("file") and c.get("enabled") == "true"]


_chests = {}


def template_chests(tdir, ref):
    """{(tier, color, size): count} of chest spawn points inside one camp template."""
    if ref not in _chests:
        out = {}
        p = os.path.join(tdir, ref + ".xml")
        if os.path.exists(p):
            for e in ET.parse(p).getroot().iter("tile"):
                m = CHEST_RE.search(e.get("name", ""))
                if m:
                    size = "big" if m.group(1).upper() == "MEDIUM" else "small"
                    color = {"VETERAN": "blue", "ELITE": "gold"}.get((m.group(2) or "").upper(), "green")
                    key = (int(m.group(3)), color, size)
                    out[key] = out.get(key, 0) + 1
        _chests[ref] = out
    return _chests[ref]


def pretty(name):
    return " - ".join(name.split("-"))


def build(src, out_dir, version=(None, None), progress=None):
    say = progress or (lambda *_: None)
    say("Counting chests and gathering spots", 0.85)
    ldir, tdir = os.path.join(src, "layouts"), os.path.join(src, "templates")
    zones = []
    for c in world_clusters(os.path.join(src, "world.xml")):
        m = TIER_RE.search(c.get("file"))
        tier = int(m.group(1)) if m else 0
        markers = [(mk.get("type"), *(float(v) for v in mk.get("pos").split())) for mk in c.iter("marker")]

        chests = {"green": 0, "blue_small": 0, "blue_big": 0, "gold_small": 0, "gold_big": 0}
        gather = []
        layout = ET.parse(os.path.join(ldir, c.get("file"))).getroot()
        for ti in layout.iter("templateinstance"):
            ref = ti.get("ref")
            x, _, z = (float(v) for v in ti.get("pos").split())
            if "_PVE_" in ref:
                for (t, color, size), n in template_chests(tdir, ref).items():
                    if t == tier:
                        chests["green" if color == "green" else f"{color}_{size}"] += n
            rm = RES_RE.match(ref)
            if rm:
                size = "big" if rm.group(1) == "M" else "small"
                near = [t for t, mx, mz in markers if t in GATHER_TYPES and abs(mx - x) < 6 and abs(mz - z) < 6]
                kinds = near or list(RES_PAIRS.get(rm.group(2), ()))
                gather.append({"type": kinds[0] if len(kinds) == 1 else "/".join(kinds), "size": size})

        dungeons = {"solo": 0, "group": 0, "elite": 0}
        for t, _, _ in markers:
            if t.startswith("dungeon_"):
                k = t.split("_", 1)[1]
                dungeons[k] = dungeons.get(k, 0) + 1
        res = {}
        for r in c.iter("resource"):
            res.setdefault(r.get("name").title(), {})[r.get("tier")] = int(r.get("count") or 0)
        conn = CONNECTIONS.get(c.get("type"), ("roads", c.get("type", "").replace("TUNNEL_", "").title()))
        gather.sort(key=lambda g: (g["size"] != "big", g["type"]))
        zones.append({
            "id": c.get("id"), "name": pretty(c.get("displayname")), "tier": tier,
            "type": c.get("type"), "conn": conn[0], "connLabel": conn[1],
            "chests": chests, "gather": gather, "dungeons": dungeons, "res": res,
        })
    zones.sort(key=lambda z: z["name"])
    os.makedirs(out_dir, exist_ok=True)
    meta = {"built": datetime.datetime.now().isoformat(timespec="seconds"),
            "version": version[0], "versionDate": version[1], "zones": len(zones)}
    for name, obj in (("zones.json", zones), ("meta.json", meta)):
        tmp = os.path.join(out_dir, name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, os.path.join(out_dir, name))
    say(f"Done: {len(zones)} zones", 1.0)
    return meta


def update(out_dir, progress=None):
    version = latest_version()
    tmp = tempfile.mkdtemp(prefix="albion_ava_")
    try:
        download(tmp, progress or (lambda *_: None))
        return build(tmp, out_dir, version, progress)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(os.path.dirname(here), "data", "game")
    show = lambda t, p: print(f"[{p * 100:5.1f}%] {t}")  # noqa: E731
    if len(sys.argv) > 1:
        print(build(sys.argv[1], out, latest_version(), show))
    else:
        print(update(out, show))
