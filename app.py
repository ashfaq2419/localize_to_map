import streamlit as st
from pathlib import Path
import subprocess
import webbrowser

st.set_page_config(page_title="Object Localization Map", layout="wide")

st.title("Object & Observer Localization Viewer")

# Select the dataset folder
root_folder = st.text_input("Enter path to dataset folder:", "./dataset_sdp")

if st.button("Generate Map"):
    folder_path = Path(root_folder).resolve()
    if not folder_path.exists():
        st.error(f"Folder not found: {folder_path}")
    else:
        st.info("Running localization algorithm...")
        # Run your existing script
        cmd = ["python3", "localize_to_map.py", "--root", str(folder_path)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        st.text(result.stdout)
        if result.returncode != 0:
            st.error(result.stderr)
        else:
            map_path = Path("results/map.html").resolve()
            if map_path.exists():
                st.success(f"Map generated at: {map_path}")
                # Display the map inside Streamlit
                st.components.v1.html(map_path.read_text(), height=600, scrolling=True)
                if st.button("Open in Browser"):
                    webbrowser.open(f"file://{map_path}")
            else:
                st.warning("Map file not found. Check logs above.")
