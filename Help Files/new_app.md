# Object & Observer Localization Viewer

A lightweight Streamlit app to visualize observers, the UAV’s actual position, and the estimated UAV position on an interactive map.

- Left panel (sidebar): controls (dataset root, case picker, clear/quit)
- Right panel: map only (with popups that can show an image + metadata for observers and the object)

The app calls ```core.build_map_for_root(...)``` to read the JSON files, run your localization, and render a Folium map.

## Features

- Pick any dataset root and a case (e.g., ```dataset_sdp/2```).
- Validates ```object_records/1/data.json``` exists before rendering.
- Popups on markers: click an observer/object pin to see an image (if present) and metadata (lat/lon/alt, yaw/pitch, etc.).
- Keeps the previously-rendered map visible across Streamlit reruns (```st.session_state```).
- “Clear Map” and “Quit App” buttons in the sidebar.

## Requirements

- Python 3.9+ (3.10–3.12 commonly used)
- Packages:
    - `streamlit` (UI)
    - `folium` (map)
    - `geopy` (distance)
    - `pyproj` (core triangulation uses it)
- (Optional) images named `photo.jpg` / `photo.jpeg` / `photo.png` placed next to each `data.json`.

Install:

```bash
pip install streamlit folium geopy pyproj
```

## Requirements

```bash
localize_to_map/
├─ new_app.py                 # Streamlit app (UI)
├─ core.py                    # Map building + localization
├─ dataset_sdp/               # Your dataset root (1/, 2/, 3/…)
│  ├─ 1/
│  │  ├─ object_records/1/data.json
│  │  ├─ observation_records/1/data.json
│  │  └─ observation_records/2/data.json
│  └─ 2/
│     └─ ...
└─ README.md
