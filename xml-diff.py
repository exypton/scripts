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


def build_visual_model(xml_before, xml_after):

    diff = main.diff_texts(
        xml_before,
        xml_after,
        formatter=formatting.DiffFormatter()
    )

    root_before = etree.fromstring(xml_before)
    root_after = etree.fromstring(xml_after)

    left = pretty_lines(xml_before)
    right = pretty_lines(xml_after)

    vis_left = []
    vis_right = []

    maxlen = max(len(left), len(right))
    for i in range(maxlen):
        vis_left.append(left[i] if i < len(left) else "")
        vis_right.append(right[i] if i < len(right) else "")

    for change in diff:

        if change["type"] == "delete":
            subtree = etree.tostring(change["value"], encoding="unicode")
            for l in pretty_lines(subtree):
                vis_left.append(l)
                vis_right.append("")

        elif change["type"] == "insert":
            subtree = etree.tostring(change["value"], encoding="unicode")
            for l in pretty_lines(subtree):
                vis_left.append("")
                vis_right.append(l)

        elif change["type"] == "update":
            path = change["node"]
            old_xml = xml_at_path(root_before, path)
            new_xml = xml_at_path(root_after, path)

            if old_xml and new_xml:
                old_lines = pretty_lines(old_xml)
                new_lines = pretty_lines(new_xml)

                for i in range(max(len(old_lines), len(new_lines))):
                    ol = old_lines[i] if i < len(old_lines) else ""
                    nl = new_lines[i] if i < len(new_lines) else ""
                    vis_left.append(ol)
                    vis_right.append(nl)

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
