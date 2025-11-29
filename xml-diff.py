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

    # Structured XML diff
    diff = main.diff_texts(
        xml_before,
        xml_after,
        formatter=formatting.XmlDiffFormatter()
    )

    # Parse original trees
    root_before = etree.fromstring(xml_before)
    root_after = etree.fromstring(xml_after)

    # Baseline for left/right
    left = pretty_lines(xml_before)
    right = pretty_lines(xml_after)

    vis_left = left[:]   # copy baseline
    vis_right = right[:] # copy baseline

    # Process structured changes
    for change in diff:
        ctype = change["type"]

        # DELETE: subtree removed
        if ctype == "delete":
            node = change["node"]
            old = root_before.xpath(node)
            if old:
                old_xml = etree.tostring(old[0], pretty_print=True, encoding="unicode")
                for ln in pretty_lines(old_xml):
                    vis_left.append(ln)
                    vis_right.append("")

        # INSERT: subtree added
        elif ctype == "insert":
            children = change.get("children", [])
            for child in children:
                xml_str = etree.tostring(child, pretty_print=True, encoding="unicode")
                for ln in pretty_lines(xml_str):
                    vis_left.append("")
                    vis_right.append(ln)

        # UPDATE: value changed
        elif ctype == "update":
            old_val = change.get("old", "")
            new_val = change.get("new", "")
            node = change["node"]

            # reconstruct the full element
            old_node = root_before.xpath(node)
            new_node = root_after.xpath(node)

            old_xml = etree.tostring(old_node[0], pretty_print=True, encoding="unicode") if old_node else old_val
            new_xml = etree.tostring(new_node[0], pretty_print=True, encoding="unicode") if new_node else new_val

            old_lines = pretty_lines(old_xml)
            new_lines = pretty_lines(new_xml)

            for i in range(max(len(old_lines), len(new_lines))):
                vis_left.append(old_lines[i] if i < len(old_lines) else "")
                vis_right.append(new_lines[i] if i < len(new_lines) else "")

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
