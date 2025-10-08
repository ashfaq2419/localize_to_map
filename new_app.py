# new_app.py
import os, signal
import streamlit as st
from pathlib import Path
import core
from importlib import reload
core = reload(core)  # ensure we load the latest core.py

st.set_page_config(page_title="Object Localization Map", layout="wide")
st.title("🗺️ Object & Observer Localization Viewer")

# --- Keep last-rendered artifacts so they don't disappear on reruns ---
if "map_html" not in st.session_state:
    st.session_state["map_html"] = None
if "metrics" not in st.session_state:
    st.session_state["metrics"] = []

# Sidebar controls: Clear + Quit
with st.sidebar:
    st.header("Session")
    if st.button("🧹 Clear Map"):
        st.session_state["map_html"] = None
        st.session_state["metrics"] = []
        st.success("Cleared the current map and metrics.")
    confirm_quit = st.checkbox("I confirm I want to quit the app")
    if st.button("🛑 Quit App", type="secondary", disabled=not confirm_quit):
        os.kill(os.getpid(), signal.SIGTERM)

# 1) Choose dataset root and scan subfolders
root_folder = st.text_input("Dataset root (contains case folders like 1, 2, 3…):", "./dataset_sdp")
root = Path(root_folder).resolve()

if not root.exists():
    st.warning(f"Folder not found: {root}")
    case_options = []
else:
    case_options = sorted([p.name for p in root.iterdir() if p.is_dir()])

# 2) Dropdown for a single case folder
selected_case = st.selectbox(
    "Select a case folder:",
    options=case_options if case_options else ["<none found>"],
    index=0
)

# 3) Other controls
cols = st.columns(3)
with cols[0]:
    object_id = st.text_input("Object ID (e.g., 1 — or 'auto' to pick first):", "1")
with cols[1]:
    uav_icon = st.text_input("UAV icon (optional PNG path):", "./uav_icon.png")
with cols[2]:
    phone_icon = st.text_input("Observer icon (optional PNG path):", "./mobile_icon.png")

# 4) Generate map (persist HTML so it stays visible)
disabled_btn = (not case_options) or (selected_case == "<none found>")
if st.button("Generate Map", type="primary", disabled=disabled_btn):
    if not root.exists():
        st.error(f"Folder not found: {root}")
    else:
        with st.spinner(f"Reading JSONs and running localization for case '{selected_case}'…"):
            result = core.build_map_for_root(
                root=root,
                uav_icon_path=Path(uav_icon) if Path(uav_icon).exists() else None,
                phone_icon_path=Path(phone_icon) if Path(phone_icon).exists() else None,
                object_id=object_id,
                only_cases=[selected_case]
            )
            # Handle both return styles: (map, metrics) or map only
            if isinstance(result, tuple):
                m, metrics = result
            else:
                m, metrics = result, []
            st.session_state["map_html"] = m.get_root().render()
            st.session_state["metrics"] = metrics
        st.success(f"Done. Showing case: {selected_case}")

# 5) Always render last map + metrics if we have them
if st.session_state["map_html"]:
    st.components.v1.html(st.session_state["map_html"], height=720, scrolling=True)

    metrics = st.session_state.get("metrics") or []
    if metrics:
        st.subheader("Estimation metrics")
        st.dataframe(metrics, use_container_width=True)

        # Download CSV
        import io, csv
        buf = io.StringIO()
        fieldnames = list(metrics[0].keys())
        writer = csv.DictWriter(buf, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(metrics)
        st.download_button(
            "Download metrics CSV",
            data=buf.getvalue(),
            file_name="uav_metrics.csv",
            mime="text/csv"
        )
else:
    st.info("Pick a dataset root, select a case from the dropdown, then click **Generate Map**.")