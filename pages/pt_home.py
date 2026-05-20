import streamlit as st
from prompt_template.template_store import list_templates, delete_template

st.markdown(
    "<style>"
    "p{line-height:1.2}"
    "div[data-testid=\"column\"]{border-left:1px solid rgba(0,0,0,0.12)!important}"
    "div[data-testid=\"column\"]:first-child{border-left:none!important}"
    "</style>",
    unsafe_allow_html=True,
)

tcol, bcol = st.columns([3, 1])
with tcol:
    st.title("📋 Prompt Templates")
with bcol:
    st.write("")
    st.write("")
    if st.button("➕ Tạo template", type="primary", use_container_width=True):
        st.session_state.pop("_edit_tid", None)
        st.switch_page("pages/pt_create.py")

st.markdown("Tạo & chạy các prompt AI tái sử dụng với `{{biến}}` điền động.")

templates = list_templates()

if not templates:
    st.info(
        "**Chưa có template nào.** Bắt đầu nhanh:\n\n"
        "1. Bấm **➕ Tạo template** ở góc phải trên.\n"
        "2. Viết system prompt, dùng `{{tên_biến}}` cho chỗ cần điền.\n"
        "3. Thêm input field khớp mỗi `{{biến}}`.\n"
        "4. Lưu xong → sang **🚀 Run Template** để chạy thử."
    )
    if st.button("➕ Tạo template đầu tiên", type="primary"):
        st.session_state.pop("_edit_tid", None)
        st.switch_page("pages/pt_create.py")
    st.stop()

# Pagination
PAGE_SIZE = 5
total_pages = max(1, (len(templates) + PAGE_SIZE - 1) // PAGE_SIZE)

if "page" not in st.session_state or st.session_state.page >= total_pages:
    st.session_state.page = 0

page = st.session_state.page
start = page * PAGE_SIZE
end = start + PAGE_SIZE
page_templates = templates[start:end]

# Table header
hdr = st.columns([3, 4, 2, 3])
hdr[0].markdown("**Name**")
hdr[1].markdown("**Description**")
hdr[2].markdown("**Model**")
hdr[3].markdown("**Actions**")

st.divider()

# Table rows
for t in page_templates:
    col1, col2, col3, col4 = st.columns([3, 4, 2, 3])

    with col1:
        st.write(f"**{t['name']}**")

    with col2:
        desc = t.get("description", "") or ""
        st.caption(desc[:100] + ("..." if len(desc) > 100 else ""))

    with col3:
        st.write(t['model'])

    with col4:
        acol1, acol2, acol3, _ = st.columns([1, 1, 1, 2], gap="small")
        with acol1:
            if st.button("▶️", key=f"run_{t['id']}"):
                st.session_state["_run_tid"] = t["id"]
                st.switch_page("pages/pt_run.py")
        with acol2:
            if st.button("✏️", key=f"edit_{t['id']}"):
                st.session_state._edit_tid = t['id']
                st.switch_page("pages/pt_create.py")
        with acol3:
            with st.popover("🗑️", key=f"del_{t['id']}"):
                st.warning(f"Delete template '{t['name']}'? This also removes execution history.")
                if st.button("Confirm Delete", key=f"confirm_{t['id']}"):
                    delete_template(t["id"])
                    st.rerun()

    st.divider()

_, outer, _ = st.columns([1, 2, 1])
with outer:
    prev_col, page_col, next_col = st.columns([1, 2, 1])
    with prev_col:
        if st.button("◀ Previous", disabled=(page == 0), use_container_width=True, key="prev_page"):
            st.session_state.page -= 1
            st.rerun()
    with page_col:
        st.markdown(f"<p style='text-align:center;margin:0;line-height:2.5'><strong>Page {page + 1} of {total_pages}</strong></p>", unsafe_allow_html=True)
    with next_col:
        if st.button("Next ▶", disabled=(page >= total_pages - 1), use_container_width=True, key="next_page"):
            st.session_state.page += 1
            st.rerun()
