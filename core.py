# core.py
import os, json, math
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import folium
from folium.features import DivIcon
from geopy.distance import geodesic

EARTH_RADIUS = 6371000  # meters

import base64
from html import escape

def _first_photo_for(json_path: Path) -> Optional[Path]:
    """Return a photo path next to data.json (photo.jpg/jpeg/png), if it exists."""
    if not json_path or not json_path.exists():
        return None
    folder = json_path.parent
    for name in ("photo.jpg", "photo.jpeg", "photo.png"):
        p = folder / name
        if p.exists():
            return p
    return None

def _make_popup_html(js: Dict, photo_path: Optional[Path], width_px: int = 240) -> str:
    """Build an HTML snippet with (optional) embedded image + a small metadata table."""
    parts = []
    # Image (embedded as base64 so it works inside Streamlit/Folium)
    if photo_path and photo_path.exists():
        try:
            data = photo_path.read_bytes()
            b64 = base64.b64encode(data).decode("ascii")
            ext = photo_path.suffix.lower().lstrip(".") or "jpeg"
            parts.append(f'<img src="data:image/{ext};base64,{b64}" width="{width_px}">')
        except Exception:
            pass

    # Metadata
    gps = js.get("gps", {}) or {}
    comp = js.get("compass", {}) or {}
    gyro = js.get("gyro", {}) or {}
    rows = []
    def row(label, value):
        if value is None:
            value = "—"
        rows.append(f"<tr><td><b>{escape(label)}</b></td><td>{escape(str(value))}</td></tr>")
    row("timestamp", js.get("timestamp"))
    row("lat", gps.get("latitude"))
    row("lon", gps.get("longitude"))
    row("alt", gps.get("altitude"))
    row("gps_acc(m)", gps.get("accuracy"))
    row("heading", comp.get("heading"))
    row("yaw_geo", gyro.get("yaw_geo_north"))
    row("yaw_mag", gyro.get("yaw_magnetic_north"))
    row("pitch", gyro.get("pitch"))
    html_tbl = "<table style='font-size:12px; margin-top:6px;'>" + "".join(rows) + "</table>"
    parts.append(html_tbl)
    return "<div>" + "".join(parts) + "</div>"


def compute_bounds(lat_lon_list: List[Tuple[float, float]], margin_m=30):
    min_lat = min(lat for lat, _ in lat_lon_list)
    max_lat = max(lat for lat, _ in lat_lon_list)
    min_lon = min(lon for _, lon in lat_lon_list)
    max_lon = max(lon for _, lon in lat_lon_list)
    margin_deg = margin_m / EARTH_RADIUS * (180 / math.pi)
    return [[min_lat - margin_deg, min_lon - margin_deg],
            [max_lat + margin_deg, max_lon + margin_deg]]

def safe_get_gps(js: Dict) -> Optional[Tuple[float, float, Optional[float]]]:
    """
    Pull lat/lon[/alt] from js["gps"] if present, else top-level.
    Returns (lat, lon, alt?) or None if missing/invalid.
    """
    node = js.get("gps", js)
    try:
        lat = float(node["latitude"])
        lon = float(node["longitude"])
        alt = node.get("altitude")
        alt = float(alt) if alt is not None else None
        return lat, lon, alt
    except Exception:
        return None

# -------------------------
# FIX 1: add object_id param
# -------------------------
def read_case(case_path: Path, object_id: str = "1") -> Tuple[
    Optional[Tuple[float, float, Optional[float]]],
    List[Tuple[int, float, float, Optional[float], Dict]]
]:
    """
    Returns:
      uav (lat, lon, alt?) or None,
      observers: list of (idx, lat, lon, alt?, raw_json)
    """
    # UAV / object
    uav = None
    obj_root = case_path / "object_records"

    # choose which object id to load
    if object_id == "auto":
        candidates = sorted(obj_root.glob("*/data.json"))
        obj_path = candidates[0] if candidates else None
    else:
        obj_path = obj_root / object_id / "data.json"

    if obj_path and obj_path.exists():
        js = json.loads(obj_path.read_text(encoding="utf-8"))
        gps = safe_get_gps(js)
        if gps:
            uav = gps

    # Observers
    observers: List[Tuple[int, float, float, Optional[float], Dict]] = []
    obs_dir = case_path / "observation_records"
    if obs_dir.exists():
        # scan up to 100 records (adjust if needed)
        for i in range(1, 101):
            j = obs_dir / str(i) / "data.json"
            if not j.exists():
                continue
            js = json.loads(j.read_text(encoding="utf-8"))
            gps = safe_get_gps(js)
            if gps:
                lat, lon, alt = gps
                observers.append((i, lat, lon, alt, js))

    return uav, observers

def run_localization_for_case(
    observers: List[Tuple[int, float, float, Optional[float], Dict]],
    extras: Dict
) -> Optional[Tuple[float, float, Optional[float], Dict]]:
    """
    Bearing-only triangulation:
      1) local ENU around first observer (meters)
      2) Build unit direction vectors from yaw (clockwise from true north)
      3) For all pairs (i,j), intersect rays and collect candidates
      4) Robust estimate: median of candidate x,y
      5) Altitude: median( tan(pitch_i) * horizontal_distance_i )
      6) Convert ENU back to lat/lon
    Returns (est_lat, est_lon, est_alt, info)
    """
    if len(observers) < 2:
        return None

    import numpy as np
    from pyproj import CRS, Transformer
    from math import sin, cos, tan, radians, isfinite

    # ---- 1) ENU origin at observer 1 ----
    o0 = observers[0]
    lat0 = float(o0[1])
    lon0 = float(o0[2])
    h0   = float(o0[3] if o0[3] is not None else 0.0)

    crs_llh = CRS.from_epsg(4979)   # WGS84 3D
    crs_ecef = CRS.from_epsg(4978)  # ECEF
    t12 = Transformer.from_crs(crs_llh, crs_ecef, always_xy=True)
    t21 = Transformer.from_crs(crs_ecef, crs_llh, always_xy=True)

    X0, Y0, Z0 = t12.transform(lon0, lat0, h0)

    def enu_from_llh(lat, lon, h):
        X, Y, Z = t12.transform(lon, lat, h)
        dx, dy, dz = X - X0, Y - Y0, Z - Z0
        slat, clat = np.sin(np.deg2rad(lat0)), np.cos(np.deg2rad(lat0))
        slon, clon = np.sin(np.deg2rad(lon0)), np.cos(np.deg2rad(lon0))
        e = (-slon,          clon,         0.0)
        n = (-clon*slat, -slon*slat,   clat)
        u = ( clon*clat,  slon*clat,   slat)
        E = e[0]*dx + e[1]*dy + e[2]*dz
        N = n[0]*dx + n[1]*dy + n[2]*dz
        U = u[0]*dx + u[1]*dy + u[2]*dz
        return E, N, U

    # Observers in ENU + angles
    P = []       # (E,N)
    yaws = []    # degrees (cw from true north)
    pitches = [] # degrees (down positive or up positive? we'll assume up-positive)
    for _, lat, lon, alt, js in observers:
        E, N, U = enu_from_llh(
            float(lat),
            float(lon),
            float(alt) if alt is not None else 0.0
        )

        # Prefer gyro yaw_geo_north, else magnetic, else compass heading
        g = (js.get("gyro", {}) or {})
        c = (js.get("compass", {}) or {})
        yaw = g.get("yaw_geo_north", g.get("yaw_magnetic_north", c.get("heading")))
        pitch = g.get("pitch")

        # Skip if yaw missing
        if yaw is None or not isfinite(float(yaw)):
            continue

        P.append((float(E), float(N)))
        yaws.append(float(yaw))
        pitches.append(float(pitch) if (pitch is not None and isfinite(float(pitch))) else None)

    if len(P) < 2:
        return None

    P = np.asarray(P, dtype=float)          # shape (M,2)
    yaws = np.asarray(yaws, dtype=float)    # shape (M,)
    pitches = np.asarray(pitches, dtype=float)  # shape (M,) with NaN allowed

    # ---- 2) Direction unit vectors from yaw ----
    # MATLAB used d = [cosd(90 - alpha); sind(90 - alpha)] == [sind(alpha); cosd(alpha)]
    # In ENU (x=East, y=North), for yaw clockwise from North:
    #   d = [sin(yaw), cos(yaw)]
    yaw_rad = np.deg2rad(yaws)
    D = np.stack([np.sin(yaw_rad), np.cos(yaw_rad)], axis=1)  # shape (M,2)

    # ---- 3) Intersections for all pairs ----
    candidates = []
    M = P.shape[0]
    for i in range(M):
        pi = P[i]
        di = D[i]
        for j in range(i+1, M):
            pj = P[j]
            dj = D[j]
            # Solve: pi + t_i di = pj + t_j dj  -> [di, -dj] [t_i; t_j] = (pj - pi)
            A = np.array([[di[0], -dj[0]],
                          [di[1], -dj[1]]], dtype=float)
            det = A[0,0]*A[1,1] - A[0,1]*A[1,0]
            if abs(det) < 1e-6:
                continue  # nearly parallel
            rhs = (pj - pi)
            t = np.linalg.solve(A, rhs)
            pu = pi + t[0] * di  # intersection in ENU
            candidates.append(pu)

    if not candidates:
        # fallback: least-squares point minimizing sum of squared distances to rays
        # (simple approximant: average of origins)
        est_E, est_N = float(P[:,0].mean()), float(P[:,1].mean())
        method = "fallback-no-intersections"
    else:
        C = np.vstack(candidates)   # shape (K,2)
        # robust: median of x and y (as in your MATLAB)
        est_E = float(np.median(C[:,0]))
        est_N = float(np.median(C[:,1]))
        method = "triangulation-median"

    # ---- 4) Altitude from pitch ----
    # distance from each observer to (est_E, est_N)
    d_horiz = np.sqrt((P[:,0] - est_E)**2 + (P[:,1] - est_N)**2)
    # use only finite pitches
    valid_pitch = np.isfinite(pitches)
    if np.any(valid_pitch):
        h_i = np.tan(np.deg2rad(pitches[valid_pitch])) * d_horiz[valid_pitch]
        if h_i.size > 0:
            est_U = float(np.median(h_i))
        else:
            est_U = 0.0
    else:
        est_U = 0.0

    # ---- 5) ENU -> LLH (plotting)
    # ENU back to ECEF at origin:
    slat, clat = np.sin(np.deg2rad(lat0)), np.cos(np.deg2rad(lat0))
    slon, clon = np.sin(np.deg2rad(lon0)), np.cos(np.deg2rad(lon0))
    e = (-slon,          clon,         0.0)
    n = (-clon*slat, -slon*slat,   clat)
    u = ( clon*clat,  slon*clat,   slat)
    dx = e[0]*est_E + n[0]*est_N + u[0]*est_U
    dy = e[1]*est_E + n[1]*est_N + u[1]*est_U
    dz = e[2]*est_E + n[2]*est_N + u[2]*est_U
    X = X0 + dx; Y = Y0 + dy; Z = Z0 + dz
    lon, lat, h = t21.transform(X, Y, Z)

    info = {
        "method": method,
        "pairs": int(len(candidates)),
        "n_obs_used": int(M),
    }
    return float(lat), float(lon), float(h), info


# ---------------------------------------------
# FIX 2: accept object_id and only_cases filter
# ---------------------------------------------
def build_map_for_root(
    root: Path,
    uav_icon_path: Optional[Path] = None,
    phone_icon_path: Optional[Path] = None,
    object_id: str = "1",
    only_cases: Optional[List[str]] = None,
    enable_popups: bool = False,           # NEW
    popup_image_width_px: int = 240        # NEW
) -> folium.Map | tuple[folium.Map, List[Dict]]:
    """
    Loops all cases (folders) under root (or a filtered subset), runs localization per case,
    and builds a single Folium map with:
      - observers (blue phone pins)
      - UAV actual (red label)
      - UAV estimated (orange label)
    If enable_popups=True, markers show image+metadata popups built from the JSON files.
    Returns: (map, metrics)
    """
    center: Optional[Tuple[float, float]] = None
    overall_bounds_pts: List[Tuple[float, float]] = []
    metrics_out: List[Dict] = []

    m = folium.Map(location=[25.0, 55.0], zoom_start=16, control_scale=True)

    obs_group = folium.FeatureGroup(name="Observers", show=True)
    uav_actual_group = folium.FeatureGroup(name="UAV (actual)", show=True)
    uav_est_group = folium.FeatureGroup(name="UAV (estimated)", show=True)

    for case_folder in sorted(os.listdir(root)):
        if only_cases and case_folder not in only_cases:
            continue
        case_path = root / case_folder
        if not case_path.is_dir():
            continue

        uav, observers = read_case(case_path, object_id=object_id)
        if not observers and not uav:
            continue

        # ---------- Observers ----------
        for idx, lat, lon, alt, js in observers:
            if center is None:
                center = (lat, lon)
            overall_bounds_pts.append((lat, lon))

            # Build popup/tooltip for this observer (if requested)
            obs_popup = None
            obs_tooltip = folium.Tooltip(f"Observer {case_folder}-{idx}")
            if enable_popups:
                obs_json_path = case_path / "observation_records" / str(idx) / "data.json"
                obs_photo = _first_photo_for(obs_json_path)
                obs_html = _make_popup_html(js, obs_photo, popup_image_width_px)
                obs_popup = folium.Popup(obs_html, max_width=popup_image_width_px + 40)

            if phone_icon_path and phone_icon_path.exists():
                icon = folium.CustomIcon(str(phone_icon_path), icon_size=(36, 36))
                folium.Marker([lat, lon], icon=icon,
                              tooltip=obs_tooltip, popup=obs_popup).add_to(obs_group)
            else:
                folium.Marker([lat, lon],
                              icon=folium.Icon(color="blue", icon="user"),
                              tooltip=obs_tooltip, popup=obs_popup).add_to(obs_group)

            # small numeric label
            folium.map.Marker(
                [lat + 0.00018, lon],
                icon=DivIcon(icon_size=(150, 36), icon_anchor=(0, 0),
                             html=f'<b style="color:#1f77b4;font-size:12pt">{idx}</b>')
            ).add_to(obs_group)

        # ---------- UAV actual (object) ----------
        uav_lat = uav_lon = None
        obj_popup = None
        if uav:
            uav_lat, uav_lon, _ = uav
            if center is None:
                center = (uav_lat, uav_lon)
            overall_bounds_pts.append((uav_lat, uav_lon))

            # Build popup/tooltip for the object (if requested)
            obj_tooltip = folium.Tooltip(f"UAV actual – case {case_folder}")
            if enable_popups:
                # Resolve which object data.json path to read
                if object_id.strip().lower() == "auto":
                    cand = sorted((case_path / "object_records").glob("*/data.json"))
                    obj_json_path = cand[0] if cand else None
                else:
                    obj_json_path = case_path / "object_records" / object_id / "data.json"

                obj_html = None
                if obj_json_path and obj_json_path.exists():
                    try:
                        obj_js = json.loads(obj_json_path.read_text(encoding="utf-8"))
                    except Exception:
                        obj_js = {}
                    obj_photo = _first_photo_for(obj_json_path)
                    obj_html = _make_popup_html(obj_js, obj_photo, popup_image_width_px)
                if obj_html:
                    obj_popup = folium.Popup(obj_html, max_width=popup_image_width_px + 40)

            if uav_icon_path and uav_icon_path.exists():
                icon = folium.CustomIcon(str(uav_icon_path), icon_size=(46, 46))
                folium.Marker([uav_lat, uav_lon], icon=icon,
                              tooltip=obj_tooltip, popup=obj_popup).add_to(uav_actual_group)
            else:
                folium.Marker([uav_lat, uav_lon],
                              icon=folium.Icon(color="red", icon="star"),
                              tooltip=obj_tooltip, popup=obj_popup).add_to(uav_actual_group)

            # red text label near the object
            folium.map.Marker(
                [uav_lat + 0.00025, uav_lon],
                icon=DivIcon(icon_size=(180, 36), icon_anchor=(0, 0),
                             html=f'<b style="color:red;font-size:13pt">UAV</b>')
            ).add_to(uav_actual_group)

        # ---------- UAV estimated (your algorithm) ----------
        extras = {"angles": []}
        for _, _, _, _, js in observers:
            gyro = js.get("gyro", {}) or {}
            compass = js.get("compass", {}) or {}
            extras["angles"].append({
                "pitch":   gyro.get("pitch"),
                "yaw_geo": gyro.get("yaw_geo_north") or gyro.get("yaw_magnetic_north"),
                "heading": compass.get("heading"),
            })

        est_lat = est_lon = est_alt = None
        info = {}
        est = run_localization_for_case(observers, extras)
        if est:
            est_lat, est_lon, est_alt, info = est
            overall_bounds_pts.append((est_lat, est_lon))

            # Compute error if we also have actual
            error_m = None
            if uav_lat is not None and uav_lon is not None:
                error_m = geodesic((est_lat, est_lon), (uav_lat, uav_lon)).meters

            tooltip_txt = f"UAV est – case {case_folder}"
            if error_m is not None:
                tooltip_txt += f" | error: {error_m:.1f} m"
            if info:
                tooltip_txt += f" | {info}"

            folium.Marker(
                [est_lat, est_lon],
                icon=folium.Icon(color="orange", icon="flag"),
                tooltip=tooltip_txt
            ).add_to(uav_est_group)

            folium.map.Marker(
                [est_lat + 0.00022, est_lon],
                icon=DivIcon(icon_size=(260, 36), icon_anchor=(0, 0),
                             html=f'<b style="color:orange;font-size:12pt">UAV est'
                                  f'{f" ({error_m:.1f} m)" if error_m is not None else ""}</b>')
            ).add_to(uav_est_group)

            # helper geometry lines (observers → est)
            for idx, lat, lon, _, _ in observers:
                folium.PolyLine(
                    [(lat, lon), (est_lat, est_lon)],
                    color='gray', weight=1, opacity=0.6
                ).add_to(uav_est_group)

            # metrics row
            row = {
                "case": case_folder,
                "n_observers": len(observers),
                "has_uav_actual": uav_lat is not None,
                "est_lat": est_lat, "est_lon": est_lon,
                "uav_lat": uav_lat, "uav_lon": uav_lon,
                "error_m": round(error_m, 3) if error_m is not None else None,
                "method": info.get("method") if isinstance(info, dict) else None,
            }
            print(f"[METRIC] case={case_folder}  n_obs={row['n_observers']}  error_m={row['error_m']}")
            metrics_out.append(row)

        # optional: distances from observers to actual UAV
        if uav_lat is not None and uav_lon is not None:
            for idx, lat, lon, _, _ in observers:
                d = geodesic((lat, lon), (uav_lat, uav_lon)).meters
                folium.map.Marker(
                    [lat - 0.0001, lon],
                    icon=DivIcon(icon_size=(150, 36), icon_anchor=(0, 0),
                                 html=f"<span style='color:green;font-size:11pt'>{d:.0f} m</span>")
                ).add_to(obs_group)

    # add groups
    obs_group.add_to(m)
    uav_actual_group.add_to(m)
    uav_est_group.add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)

    # center & bounds
    if center:
        m.location = [center[0], center[1]]
    if overall_bounds_pts:
        bounds = compute_bounds(overall_bounds_pts, margin_m=30)
        m.fit_bounds(bounds)

    return m, metrics_out
