from xmldiff import main, formatting
from lxml import etree
import difflib


def pretty_lines(xml_str: str):
    parser = etree.XMLParser(remove_blank_text=True)
    root = etree.fromstring(xml_str, parser=parser)
    formatted = etree.tostring(root, pretty_print=True, encoding="unicode")
    return formatted.splitlines()


def xml_at_path(root, xpath):
    el = root.xpath(xpath)
    if not el:
        return None
    return etree.tostring(el[0], pretty_print=True, encoding="unicode")

def _value_to_element_string(val):
    """
    Helper that converts xmldiff 'value' into a pretty XML string.
    Handles lxml Elements or plain strings. Returns None if not possible.
    """
    try:
        if val is None:
            return None
        # If it's already an lxml element
        if hasattr(val, "tag"):
            return etree.tostring(val, pretty_print=True, encoding="unicode")
        # If it's a bytes/str containing XML
        if isinstance(val, (bytes, str)):
            s = val.decode() if isinstance(val, bytes) else val
            # try to parse to ensure well-formed; if it fails, just return raw string
            try:
                # Wrap in root if fragment
                parsed = etree.fromstring(s)
                return etree.tostring(parsed, pretty_print=True, encoding="unicode")
            except Exception:
                return s
    except Exception as exc:
        print("WARN: _value_to_element_string failed:", exc)
        return None


def build_visual_model(xml_before, xml_after):
    """
    Robust builder that returns two lists: vis_left, vis_right suitable for HtmlDiff.
    This version is defensive: it won't crash if xmldiff returns strings instead of elements.
    """

    # 1) Compute structural diff
    try:
        diff = main.diff_texts(
            xml_before,
            xml_after,
            formatter=formatting.DiffFormatter()
        )
    except Exception as e:
        print("ERROR: xmldiff.diff_texts failed:", e)
        # fallback: do a simple line-based alignment
        left = pretty_lines(xml_before)
        right = pretty_lines(xml_after)
        # pad to same length and return
        maxlen = max(len(left), len(right))
        vis_left = [left[i] if i < len(left) else "" for i in range(maxlen)]
        vis_right = [right[i] if i < len(right) else "" for i in range(maxlen)]
        return vis_left, vis_right

    # 2) Prepare tree roots for xpath lookups
    try:
        root_before = etree.fromstring(xml_before)
    except Exception:
        root_before = None
    try:
        root_after = etree.fromstring(xml_after)
    except Exception:
        root_after = None

    # 3) Baseline pretty-printed lines
    left = pretty_lines(xml_before)
    right = pretty_lines(xml_after)
    vis_left = []
    vis_right = []

    # Start with aligned baseline (keeps difflib happy)
    maxlen = max(len(left), len(right))
    for i in range(maxlen):
        vis_left.append(left[i] if i < len(left) else "")
        vis_right.append(right[i] if i < len(right) else "")

    # 4) Process changes from xmldiff in a defensive way
    # diff is expected to be an iterable of change dicts, but be defensive
    change_count = 0
    for change in diff:
        change_count += 1
        try:
            ctype = change.get("type") if isinstance(change, dict) else None
        except Exception:
            ctype = None

        # handle delete
        if ctype == "delete":
            raw = change.get("value", None) if isinstance(change, dict) else None
            subtree_xml = _value_to_element_string(raw) or str(raw) or ""
            for ln in (pretty_lines(subtree_xml) if subtree_xml else [""]):
                vis_left.append(ln)
                vis_right.append("")

        # handle insert
        elif ctype == "insert":
            raw = change.get("value", None) if isinstance(change, dict) else None
            subtree_xml = _value_to_element_string(raw) or str(raw) or ""
            for ln in (pretty_lines(subtree_xml) if subtree_xml else [""]):
                vis_left.append("")
                vis_right.append(ln)

        # handle update (value change)
        elif ctype == "update":
            node_path = change.get("node") if isinstance(change, dict) else None
            # attempt to pull full element string from both trees by xpath
            old_xml = None
            new_xml = None
            if node_path and root_before is not None:
                try:
                    found = root_before.xpath(node_path)
                    if found:
                        old_xml = etree.tostring(found[0], pretty_print=True, encoding="unicode")
                except Exception:
                    old_xml = None
            if node_path and root_after is not None:
                try:
                    found = root_after.xpath(node_path)
                    if found:
                        new_xml = etree.tostring(found[0], pretty_print=True, encoding="unicode")
                except Exception:
                    new_xml = None

            # fallback: if xmldiff provided the value directly
            if old_xml is None:
                # try using change['old'] or previous value fields
                old_candidate = change.get("old", None) if isinstance(change, dict) else None
                old_xml = _value_to_element_string(old_candidate) or old_xml

            if new_xml is None:
                new_candidate = change.get("value", None) if isinstance(change, dict) else None
                new_xml = _value_to_element_string(new_candidate) or new_xml

            # now convert to lines and append aligned
            old_lines = pretty_lines(old_xml) if old_xml else [""]
            new_lines = pretty_lines(new_xml) if new_xml else [""]
            for i in range(max(len(old_lines), len(new_lines))):
                vis_left.append(old_lines[i] if i < len(old_lines) else "")
                vis_right.append(new_lines[i] if i < len(new_lines) else "")

        else:
            # unknown change type -> be conservative and log
            # try to stringify the change
            try:
                sval = str(change)
            except Exception:
                sval = "<unprintable change>"
            vis_left.append(f"<!-- UNHANDLED CHANGE: {sval} -->")
            vis_right.append("")

    # final debug info
    print(f"build_visual_model: baseline left={len(left)} right={len(right)},"
          f" changes_processed={change_count}, vis_left={len(vis_left)}, vis_right={len(vis_right)}")

    return vis_left, vis_right

def add_collapsible_sections(html, threshold=8):
    rows = html.splitlines()
    new_rows = []
    buffer_block = []
    unchanged_count = 0
    in_table = False

    for row in rows:
        if "<tbody>" in row:
            in_table = True
        if "</tbody>" in row:
            in_table = False

        if in_table and 'class="diff_unmodified"' in row:
            buffer_block.append(row)
            unchanged_count += 1
        else:
            if unchanged_count >= threshold:
                new_rows.append(
                    f"<tr><td colspan='4' style='text-align:center;'>"
                    f"<button onclick=\"this.nextElementSibling.style.display='block'; this.style.display='none';\">"
                    f"Show {unchanged_count} unchanged lines..."
                    f"</button></td></tr>"
                )
                new_rows.append("<tbody style='display:none;'>")
                new_rows.extend(buffer_block)
                new_rows.append("</tbody>")
            else:
                new_rows.extend(buffer_block)

            buffer_block = []
            unchanged_count = 0
            new_rows.append(row)

    return "\n".join(new_rows)


def generate_html_diff(current_file,
                       candidate_file,
                       output_html,
                       device_name="Device"):

    with open(current_file, "r", encoding="utf-8") as f:
        xml_before = f.read()

    with open(candidate_file, "r", encoding="utf-8") as f:
        xml_after = f.read()

    left_lines, right_lines = build_visual_model(xml_before, xml_after)

    diff_html = difflib.HtmlDiff(
        tabsize=4,
        wrapcolumn=120
    ).make_file(
        left_lines,
        right_lines,
        fromdesc=f"Current Configuration ({device_name})",
        todesc=f"Candidate Configuration ({device_name})"
    )

    diff_html = add_collapsible_sections(diff_html)

    with open(output_html, "w", encoding="utf-8") as f:
        f.write(diff_html)

    print(f"✔ Combined diff written to: {output_html}")


if __name__ == "__main__":
    generate_html_diff(
        "current_config.xml",
        "candidate_config.xml",
        "combined_diff.html",
        device_name="R1"
    )
