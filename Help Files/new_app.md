# Object & Observer Localization Viewer

A lightweight Streamlit app to visualize observers, the UAV’s actual position, and the estimated UAV position on an interactive map.

- Left panel (sidebar): controls (dataset root, case picker, clear/quit)
- Right panel: map only (with popups that can show an image + metadata for observers and the object)

The app calls ```core.build_map_for_root(...)``` to read the JSON files, run your localization, and render a Folium map.