# new_app.py
import os, signal
from importlib import reload
from pathlib import Path

import streamlit as st
import core
core = reload(core)  # ensure latest core.py is used each rerun

st.set_page_config(page_title="Object Localization Map", layout="wide")

# ---- session state ----
if "map_html" not in st.session_state:
    st.session_state["map_html"] = None

# ===== Sidebar: all controls =====
with st.sidebar:
    # move title to sidebar
    st.title("Object & Observer Localization Viewer")

    st.header("Session")
    if st.button("Clear Map"):
        st.session_state["map_html"] = None
        st.success("Cleared map.")

    confirm_quit = st.checkbox("I confirm I want to quit the app")
    if st.button("Quit App", type="secondary", disabled=not confirm_quit):
        os.kill(os.getpid(), signal.SIGTERM)

    st.markdown("---")
    st.header("Controls")

    # 1) dataset root
    root_folder = st.text_input("Dataset root (folders 1,2,3…):", "./dataset_sdp")
    root = Path(root_folder).resolve()

    # discover case folders
    if not root.exists():
        st.warning(f"Folder not found: {root}")
        case_options = []
    else:
        case_options = sorted([p.name for p in root.iterdir() if p.is_dir()])

    # 2) case dropdown
    selected_case = st.selectbox(
        "Select a case folder:",
        options=case_options if case_options else ["<none found>"],
        index=0
    )

    # 3) generate
    disabled_btn = (not case_options) or (selected_case == "<none found>")
    if st.button("Generate Map", type="primary", disabled=disabled_btn):
        if not root.exists():
            st.error(f"Folder not found: {root}")
            st.stop()

        # Verify object_records/1/data.json exists
        obj_json = root / selected_case / "object_records" / "1" / "data.json"
        if not obj_json.exists():
            st.session_state["map_html"] = None
            st.error(
                f"No object JSON found for case **{selected_case}**."
            )
            st.stop()

        # Build the map (object_id always '1')
        with st.spinner(f"Running localization for case '{selected_case}'…"):
            result = core.build_map_for_root(
                root=root,
                object_id="1",               # <--- always use "1"
                only_cases=[selected_case],
                enable_popups=True,           # rich popups (images + metadata)
                popup_image_width_px=240
            )
            m = result[0] if isinstance(result, tuple) else result
            st.session_state["map_html"] = m.get_root().render()
        st.success(f"Map ready for case {selected_case}")

# ===== Main: map only =====
if st.session_state["map_html"]:
    st.components.v1.html(st.session_state["map_html"], height=760, scrolling=True)
else:
    st.info("Use the controls in the left sidebar: pick the dataset root and case, then click **Generate Map**.")
