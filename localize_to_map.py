#!/usr/bin/env python3
import json
import argparse
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import folium

# ----------------------------
# Helpers
# ----------------------------
def find_first(d: Dict[str, Any], candidates: List[str]) -> Optional[Any]:
    lower_map = {k.lower(): k for k in d.keys()}
    for cand in candidates:
        if cand.lower() in lower_map:
            return d[lower_map[cand.lower()]]
    for v in d.values():
        if isinstance(v, dict):
            hit = find_first(v, candidates)
            if hit is not None:
                return hit
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    hit = find_first(item, candidates)
                    if hit is not None:
                        return hit
    return None

def extract_lat_lon_alt(js: Dict[str, Any]) -> Optional[Tuple[float, float, Optional[float]]]:
    lat_candidates = ["lat", "latitude", "y"]
    lon_candidates = ["lon", "lng", "longitude", "x"]
    alt_candidates = ["alt", "altitude", "z", "h"]

    lat = find_first(js, lat_candidates)
    lon = find_first(js, lon_candidates)
    alt = find_first(js, alt_candidates)

    if lat is None or lon is None:
        return None
    try:
        return float(lat), float(lon), (float(alt) if alt is not None else None)
    except (TypeError, ValueError):
        return None

def read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[WARN] Could not read JSON: {path} ({e})")
        return None

# ----------------------------
# Loading dataset
# ----------------------------
def load_object(root: Path, session: str, object_folder: str = "object_records", object_id: str = "1") -> Optional[Dict[str, Any]]:
    obj_json = root / session / object_folder / object_id / "data.json"
    if not obj_json.exists():
        print(f"[INFO] Object {session} location missing (no JSON file found at {obj_json})")
        return None

    js = read_json(obj_json)
    if js is None:
        print(f"[INFO] Object {session} location missing (invalid JSON: {obj_json})")
        return None

    coords = extract_lat_lon_alt(js.get("gps", js))
    if coords:
        lat, lon, alt = coords
        return {
            "session": session,
            "source": str(obj_json),
            "lat": lat, "lon": lon, "alt": alt
        }
    else:
        print(f"[INFO] Object {session} location missing (no lat/lon found in {obj_json})")
        return None

def load_observations(root: Path, session: str, obs_folder: str = "observation_records") -> List[Dict[str, Any]]:
    out = []
    base = root / session / obs_folder
    if not base.exists():
        return out
    for leaf in sorted(base.glob("*")):
        if not leaf.is_dir():
            continue
        j = leaf / "data.json"
        if j.exists():
            js = read_json(j)
            if js is None:
                continue
            coords = extract_lat_lon_alt(js)
            if coords:
                lat, lon, alt = coords
                label = find_first(js, ["id", "name", "label"]) or leaf.name
                ts = find_first(js, ["timestamp", "time", "datetime"])
                out.append({
                    "session": session,
                    "record": leaf.name,
                    "source": str(j),
                    "lat": lat, "lon": lon, "alt": alt,
                    "label": str(label),
                    "timestamp": str(ts) if ts else None
                })
    return out

# ----------------------------
# GeoJSON + Map
# ----------------------------
def to_geojson(observers: List[Dict[str, Any]], obj: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    feats = []
    for cam in observers:
        props = {
            "type": "observer",
            "session": cam["session"],
            "record": cam["record"],
            "label": cam.get("label"),
            "timestamp": cam.get("timestamp"),
            "source": cam["source"]
        }
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [cam["lon"], cam["lat"]]},
            "properties": props
        })
    if obj is not None:
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [obj["lon"], obj["lat"]]},
            "properties": {
                "type": "object",
                "session": obj["session"],
                "source": obj["source"]
            }
        })
    return {"type": "FeatureCollection", "features": feats}

SESSION_COLORS = ["blue", "green", "purple", "orange", "darkred", "cadetblue", "darkgreen"]

def make_map(observers: List[Dict[str, Any]], objects: List[Dict[str, Any]], out_html: Path) -> Path:
    if not observers and not obj:
        raise RuntimeError("No valid coordinates found to plot.")

    if observers:
        center_lat, center_lon = observers[0]["lat"], observers[0]["lon"]
    else:
        center_lat, center_lon = obj["lat"], obj["lon"]  # type: ignore

    m = folium.Map(location=[center_lat, center_lon], zoom_start=17, control_scale=True)
    from collections import defaultdict
    groups = defaultdict(list)
    for cam in observers:
        groups[cam["session"]].append(cam)

    for idx, (session, cams) in enumerate(sorted(groups.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else kv[0])):
        color = SESSION_COLORS[idx % len(SESSION_COLORS)]
        fg = folium.FeatureGroup(name=f"Session {session}", show=True)
        for cam in cams:
            popup_lines = [
                f"<b>Session:</b> {cam['session']}",
                f"<b>Record:</b> {cam['record']}",
                f"<b>Label:</b> {cam.get('label','')}",
                f"<b>Time:</b> {cam.get('timestamp','')}",
                f"<b>Source:</b> {cam['source']}"
            ]
            folium.Marker(
                [cam["lat"], cam["lon"]],
                popup=folium.Popup("<br>".join(popup_lines), max_width=350),
                icon=folium.Icon(color=color, icon="user")
            ).add_to(fg)
        fg.add_to(m)

        if objects:
            obj_fg = folium.FeatureGroup(name="Objects", show=True)
            for obj in objects:
                popup = folium.Popup(
                    f"<b>OBJECT</b><br><b>Session:</b> {obj['session']}<br><b>Source:</b> {obj['source']}",
                    max_width=300
                )
                folium.Marker(
                    [obj["lat"], obj["lon"]],
                    popup=popup,
                    icon=folium.Icon(color="red", icon="star")
                ).add_to(obj_fg)
            obj_fg.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    m.save(str(out_html))
    return out_html

# ----------------------------
# Main
# ----------------------------
def main():
    ap = argparse.ArgumentParser(description="Read folders 1..9 and plot observers + object on a map.")
    ap.add_argument("--root", type=Path, default=Path("./dataset_sdp"),
                    help="Path to dataset root (default: ./dataset_sdp)")
    ap.add_argument("--first", type=int, default=1)
    ap.add_argument("--last", type=int, default=9)
    ap.add_argument("--object-folder", default="object_records")
    ap.add_argument("--object-id", default="1")
    ap.add_argument("--obs-folder", default="observation_records")
    ap.add_argument("--out-geojson", type=Path, default=Path("./results/results.geojson"))
    ap.add_argument("--out-map", type=Path, default=Path("./results/map.html"))
    args = ap.parse_args()

    # Create results folder if missing
    results_dir = args.out_map.parent
    results_dir.mkdir(parents=True, exist_ok=True)

    print(f"[INFO] Using dataset root: {args.root.resolve()}")

    observers: List[Dict[str, Any]] = []
    obj_any: Optional[Dict[str, Any]] = None
    objects = []

    for s in range(args.first, args.last + 1):
        session = str(s)
        obj = load_object(args.root, session, args.object_folder, args.object_id)
        if obj:
            objects.append(obj)
        observers.extend(load_observations(args.root, session, args.obs_folder))

    print("[INFO] Objects found for sessions:", [o["session"] for o in objects])
    geojson = to_geojson(observers, obj_any)
    with open(args.out_geojson, "w", encoding="utf-8") as f:
        json.dump(geojson, f, indent=2)
    print(f"[OK] Wrote GeoJSON -> {args.out_geojson.resolve()}")

    #out_map = make_map(observers, obj_any, args.out_map)
    out_map = make_map(observers, objects, args.out_map)

    print(f"[OK] Wrote map -> {out_map.resolve()}")

if __name__ == "__main__":
    main()
