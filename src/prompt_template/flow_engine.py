import base64
import os
import re
import uuid

from prompt_template.template_store import get_template, get_flow_bindings
import prompt_template.llm_client as _llm


def replace_variables(prompt, values):
    """Replace ``{{key}}`` placeholders with corresponding values."""

    def replacer(match):
        key = match.group(1).strip()
        return str(values.get(key, match.group(0)))

    return re.sub(r"\{\{\s*(\w+)\s*\}\}", replacer, prompt)


def _save_media_to_file(response_data, output_type):
    """Convert response_data (data URI / URL / file path) to a local file path.
    Returns absolute path to the saved file, or None if conversion fails.
    """
    if not response_data:
        return None

    if os.path.exists(response_data):
        return os.path.abspath(response_data)

    if response_data.startswith("data:"):
        try:
            header, _, b64 = response_data.partition(",")
            mime = header.split(";")[0].split(":")[1]
            ext = mime.split("/")[-1]
            if ext == "octet-stream":
                ext = "bin"
            filename = "flow_media_{}.{}".format(uuid.uuid4().hex, ext)
            filepath = os.path.join("uploads", filename)
            with open(filepath, "wb") as f:
                f.write(base64.b64decode(b64))
            return os.path.abspath(filepath)
        except Exception:
            return None

    if response_data.startswith(("http://", "https://")):
        try:
            import requests
            resp = requests.get(response_data, timeout=30)
            resp.raise_for_status()
            ext = "bin"
            ct = resp.headers.get("content-type", "")
            if ct:
                ext = ct.split("/")[-1].split(";")[0]
            filename = "flow_media_{}.{}".format(uuid.uuid4().hex, ext)
            filepath = os.path.join("uploads", filename)
            with open(filepath, "wb") as f:
                f.write(resp.content)
            return os.path.abspath(filepath)
        except Exception:
            return None

    return None


def _extract_child_values(values_by_group, parent_key):
    """Extract values belonging to a sub-flow from the flat values_by_group dict.
    {"summary__raw_data": {...}} with parent_key="summary"
    returns {"raw_data": {...}}
    """
    prefix = parent_key + "__"
    child = {}
    for k, v in values_by_group.items():
        if k.startswith(prefix):
            child[k[len(prefix):]] = v
    return child


def get_flow_input_groups(template_id, _visited=None):
    """Recursively collect leaf-node input groups for a flow template.
    Returns list of dicts, each with:
        path: list of output_key ancestry chain
        path_display: 'key1 -> key2' string
        template_id: leaf template's id
        template_name: leaf template's name
        inputs: list of field dicts from the leaf template
        output_key: key in the immediate parent flow
    Returns [] if template is not a flow or has no bindings.
    """
    if _visited is None:
        _visited = set()
    if template_id in _visited:
        return []
    _visited.add(template_id)

    template = get_template(template_id)
    if not template or not template.get("is_flow"):
        return []

    bindings = get_flow_bindings(template_id)
    groups = []

    for binding in bindings:
        sub = get_template(binding["sub_template_id"])
        if not sub:
            continue

        if sub.get("is_flow"):
            nested = get_flow_input_groups(sub["id"], _visited)
            for g in nested:
                g["path"] = [binding["output_key"]] + g["path"]
                g["path_display"] = "  ->  ".join(g["path"])
            groups.extend(nested)
        else:
            groups.append({
                "path": [binding["output_key"]],
                "path_display": binding["output_key"],
                "template_id": sub["id"],
                "template_name": sub["name"],
                "inputs": sub.get("inputs", []),
                "output_key": binding["output_key"],
            })

    return groups


def execute_flow(template, values_by_group, _visited=None):
    """Recursively execute a flow template.
    args:
        template: dict from get_template() (the flow template).
        values_by_group: dict of {group_key: {field: val, _files: [paths]}}
            group_key is the path joined by "__" e.g. "summary__raw_data".
    returns dict with keys: text, type, response_data, candidates
        (same interface as llm_client.generate())
    """
    if _visited is None:
        _visited = set()
    if template["id"] in _visited:
        return {"text": "", "type": "text", "response_data": "", "candidates": []}
    _visited.add(template["id"])

    bindings = get_flow_bindings(template["id"])
    text_replacements = {}
    media_files = []

    for binding in bindings:
        sub = get_template(binding["sub_template_id"])
        if not sub:
            continue

        if sub.get("is_flow"):
            child_values = _extract_child_values(values_by_group, binding["output_key"])
            result = execute_flow(sub, child_values, _visited)
        else:
            leaf_data = values_by_group.get(binding["output_key"], {})
            leaf_files = leaf_data.pop("_files", []) if isinstance(leaf_data, dict) else []
            leaf_clean = {k: v for k, v in leaf_data.items() if k != "_files"} if isinstance(leaf_data, dict) else {}
            sub_prompt = replace_variables(sub["system_prompt"], leaf_clean)
            result = _llm.generate(
                system_prompt=sub["system_prompt"],
                user_prompt=sub_prompt,
                model=sub["model"],
                temperature=sub["temperature"],
                files=leaf_files or None,
            )

        if result["type"] == "text":
            text_replacements[binding["output_key"]] = result["text"]
        else:
            saved = _save_media_to_file(result.get("response_data", ""), result["type"])
            if saved:
                media_files.append(saved)

    main_data = values_by_group.get("_main", {})
    main_files = []
    main_clean = {}
    if isinstance(main_data, dict):
        main_files = main_data.pop("_files", []) if "_files" in main_data else []
        main_clean = {k: v for k, v in main_data.items() if k != "_files"}

    merged_text = {}
    merged_text.update(main_clean)
    merged_text.update(text_replacements)
    final_prompt = replace_variables(template["system_prompt"], merged_text)

    all_files = main_files + media_files

    result = _llm.generate(
        system_prompt=template["system_prompt"],
        user_prompt=final_prompt,
        model=template["model"],
        temperature=template["temperature"],
        files=all_files or None,
    )

    return result
