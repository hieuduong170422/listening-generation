import streamlit as st
import json
from prompt_template.history_store import list_history, get_history_entry, delete_history

st.title("📜 Execution History")

entries = list_history()

if entries:
    col1, col2 = st.columns([6, 1])
    with col2:
        with st.popover("🗑️ Clear All"):
            st.warning("Clear ALL execution history? This cannot be undone.")
            if st.button("Confirm Clear All", type="primary"):
                for e in entries:
                    delete_history(e["id"])
                st.rerun()

if not entries:
    st.info("No execution history yet. Run a template to see results here.")
    st.stop()

for entry in entries:
    with st.container(border=True):
        col1, col2, col3, col4 = st.columns([2.5, 2, 1.5, 0.5])

        with col1:
            st.write(f"**{entry['template_name']}**")
            st.caption(entry.get("created_at", ""))

        with col2:
            st.write(f"Model: {entry['model']}")
            st.write(f"Type: {entry['response_type']}")

        with col3:
            try:
                inputs = json.loads(entry.get("inputs_json", "{}"))
                st.write(f"Inputs: {len(inputs)} field(s)")
            except (json.JSONDecodeError, TypeError):
                st.write("Inputs: -")

        with col4:
            with st.popover("🗑️", key=f"del_pop_{entry['id']}"):
                st.warning(f"Delete entry for '{entry['template_name']}'?")
                if st.button("Confirm Delete", key=f"confirm_del_{entry['id']}"):
                    delete_history(entry["id"])
                    st.rerun()

        with st.expander("View Details"):
            st.write("**Inputs:**")
            try:
                inputs = json.loads(entry.get("inputs_json", "{}"))
                st.json(inputs)
            except (json.JSONDecodeError, TypeError):
                st.write(entry.get("inputs_json", ""))

            st.write("**Response:**")
            response_text = entry.get("response_text", "")
            response_type = entry.get("response_type", "text")
            response_data = entry.get("response_data", "")

            if response_type == "image":
                img_src = response_data or response_text
                st.image(img_src)
            elif response_type == "video":
                vid_src = response_data or response_text
                st.video(vid_src)
            elif response_type == "audio":
                aud_src = response_data or response_text
                st.audio(aud_src)
            else:
                st.markdown(response_text if response_text else "*No response text*")

            st.write("**Metadata:**")
            st.json(
                {
                    "model": entry["model"],
                    "temperature": entry.get("temperature"),
                    "response_type": entry["response_type"],
                    "created_at": entry.get("created_at"),
                }
            )
