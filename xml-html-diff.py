"""
xml_context_structural_html_diff.py

Produces an HtmlDiff-like side-by-side HTML that shows only context blocks
around structural XML changes, but preserves full parent tags for each change.

Requirements:
    pip install lxml xmldiff

Usage example:
    python xml_context_structural_html_diff.py before.xml after.xml out.html --device R1 --siblings 1
"""

from lxml import etree
from xmldiff import main, formatting
import difflib
import argparse
from typing import List, Tuple
from collections import OrderedDict


# --- helpers -------------------------------------------------------

def qname_local(tag):
    """Return localname for a possibly namespaced tag."""
    if tag is None:
        return ""
    if isinstance(tag, etree.QName):
        return tag.localname
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def pretty_lines_of_element(elem: etree._Element) -> List[str]:
    """Return pretty-printed lines for an element."""
    s = etree.tostring(elem, pretty_print=True, encoding="unicode")
    return s.splitlines()


def open_tag_line(elem: etree._Element, depth: int) -> str:
    """Produce an opening tag line with attributes in pretty style."""
    tag = qname_local(elem.tag)
    # build attribute text
    attrs = " ".join(f'{k}="{v}"' for k, v in elem.attrib.items())
    if attrs:
        return ("  " * depth) + f"<{tag} {attrs}>"
    else:
        return ("  " * depth) + f"<{tag}>"


def close_tag_line(elem: etree._Element, depth: int) -> str:
    tag = qname_local(elem.tag)
    return ("  " * depth) + f"</{tag}>"


def minimal_wrapper_for(path_elems: List[etree._Element],
                        inner_lines: List[str]) -> List[str]:
    """
    Given a list of ancestor elements [root, ..., parent] and inner lines
    (which are already pretty-printed and include indentation), build a
    minimal block that shows opening tags, the inner_lines (indented one level),
    and closing tags.
    """
    lines: List[str] = []
    # open all ancestors
    for depth, anc in enumerate(path_elems):
        lines.append(open_tag_line(anc, depth))
    # indent inner lines one more level than last ancestor
    indent = "  " * len(path_elems)
    for ln in inner_lines:
        if ln.strip() == "":
            lines.append(indent + ln)
        else:
            lines.append(indent + ln)
    # close in reverse order
    for depth, anc in enumerate(reversed(path_elems)):
        lines.append(close_tag_line(anc, len(path_elems) - depth - 1))
    return lines


def find_child_slice(parent: etree._Element, target: etree._Element, siblings: int):
    """
    From parent's children, find index of target and return a slice of children
    from idx-siblings .. idx+siblings inclusive (clamped).
    Returns list of child elements.
    """
    children = [c for c in parent if isinstance(c.tag, str)]
    # find target by identity (object) or by matching tag+text/attrib
    idx = None
    for i, c in enumerate(children):
        if c is target:
            idx = i
            break
        # fallback heuristics
        if etree.tostring(c) == etree.tostring(target):
            idx = i
            break
    if idx is None:
        # not found; return just the target
        return [target]
    lo = max(0, idx - siblings)
    hi = min(len(children) - 1, idx + siblings)
    return children[lo:hi + 1]


# --- core builder -------------------------------------------------

def build_context_blocks(xml_before: str,
                         xml_after: str,
                         sibling_count: int = 0) -> List[Tuple[List[str], List[str]]]:
    """
    Returns a list of (left_block_lines, right_block_lines) for each change.
    Each block contains the minimal ancestor wrapper plus either the deleted/inserted/updated subtree.
    sibling_count controls how many sibling child elements (on each side) to include around the changed element.
    """

    # structured diff formatter
    diff = main.diff_texts(xml_before, xml_after, formatter=formatting.XmlDiffFormatter())

    root_before = etree.fromstring(xml_before)
    root_after = etree.fromstring(xml_after)

    blocks = []
    seen_paths = set()  # deduplicate identical node paths

    for change in diff:
        ctype = change.get("type")
        node_path = change.get("node")  # xpath-like string

        # dedupe by node path (some formatters may produce duplicates)
        key = (ctype, node_path, str(change.get("position", "")))
        if key in seen_paths:
            continue
        seen_paths.add(key)

        # We'll try to get the element references from before/after roots
        left_block = []
        right_block = []

        if ctype == "delete":
            # node existed in before but not after
            found = root_before.xpath(node_path)
            if not found:
                # fallback: represent as a simple comment line
                left_block = [f"<!-- deleted {node_path} -->"]
                right_block = [""]
            else:
                target = found[0]
                parent = target.getparent()
                ancestors = []
                # collect ancestors from root down to parent
                a = parent
                stack = []
                while a is not None:
                    stack.insert(0, a)
                    a = a.getparent()
                ancestors = stack
                # choose the slice of siblings to include from parent's children
                slice_children = find_child_slice(parent, target, sibling_count)
                inner_lines = []
                for child in slice_children:
                    inner_lines.extend(pretty_lines_of_element(child))
                left_block = minimal_wrapper_for(ancestors, inner_lines)
                # right side empty (deleted)
                right_block = [""] * len(left_block)

        elif ctype == "insert":
            # node exists in after but not before
            found = root_after.xpath(node_path)
            if not found:
                left_block = [""]
                right_block = [f"<!-- inserted {node_path} -->"]
            else:
                target = found[0]
                parent = target.getparent()
                # ancestors from root..parent
                a = parent
                stack = []
                while a is not None:
                    stack.insert(0, a)
                    a = a.getparent()
                ancestors = stack
                slice_children = find_child_slice(parent, target, sibling_count)
                inner_lines = []
                for child in slice_children:
                    inner_lines.extend(pretty_lines_of_element(child))
                right_block = minimal_wrapper_for(ancestors, inner_lines)
                left_block = [""] * len(right_block)

        elif ctype == "update":
            # node present in both but value changed
            # try to get element in both trees
            found_b = root_before.xpath(node_path)
            found_a = root_after.xpath(node_path)
            # pick parent from before or after
            parent = None
            if found_b:
                target_b = found_b[0]
                parent = target_b.getparent()
            elif found_a:
                target_a = found_a[0]
                parent = target_a.getparent()

            if parent is None:
                # fallback: simple textual representation
                old = change.get("old", "")
                new = change.get("new", "")
                left_block = [str(old)]
                right_block = [str(new)]
            else:
                # collect ancestor list
                a = parent
                stack = []
                while a is not None:
                    stack.insert(0, a)
                    a = a.getparent()
                ancestors = stack

                # choose sibling slices for each side separately
                inner_left = []
                inner_right = []

                if found_b:
                    target_b = found_b[0]
                    slice_b = find_child_slice(parent, target_b, sibling_count)
                    for child in slice_b:
                        inner_left.extend(pretty_lines_of_element(child))
                if found_a:
                    target_a = found_a[0]
                    slice_a = find_child_slice(parent, target_a, sibling_count)
                    for child in slice_a:
                        inner_right.extend(pretty_lines_of_element(child))

                # Build wrapped blocks; ensure they have same line counts by padding
                left_block = minimal_wrapper_for(ancestors, inner_left or [""])
                right_block = minimal_wrapper_for(ancestors, inner_right or [""])
                # pad the shorter with empty lines so HtmlDiff aligns them properly
                if len(left_block) < len(right_block):
                    left_block.extend([""] * (len(right_block) - len(left_block)))
                elif len(right_block) < len(left_block):
                    right_block.extend([""] * (len(left_block) - len(right_block)))

        else:
            # unknown change: append a simple placeholder
            left_block = [f"<!-- unhandled change: {change} -->"]
            right_block = [""]

        # store block
        blocks.append((left_block, right_block))

    return blocks


# --- compose final aligned lists and render -----------------------

def render_blocks_to_html(blocks: List[Tuple[List[str], List[str]]],
                          output_html: str,
                          device_name: str = "Device"):
    """
    Compose blocks into two aligned lists and render HtmlDiff.
    We separate blocks with a small ellipsis indicator row for readability.
    """
    left_lines = []
    right_lines = []
    sep = ["..."]  # a visible separator line

    for i, (lblock, rblock) in enumerate(blocks):
        if i > 0:
            # insert a small gap between blocks
            left_lines.extend(sep)
            right_lines.extend(sep)
        left_lines.extend(lblock)
        right_lines.extend(rblock)

    # If there were no changes, show a short message
    if not left_lines and not right_lines:
        left_lines = ["<!-- no changes found -->"]
        right_lines = ["<!-- no changes found -->"]

    html = difflib.HtmlDiff(tabsize=4, wrapcolumn=120).make_file(
        fromlines=left_lines,
        tolines=right_lines,
        fromdesc=f"Current Configuration ({device_name})",
        todesc=f"Candidate Configuration ({device_name})"
    )

    with open(output_html, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✔ Written {output_html} (blocks={len(blocks)})")

# --- PUBLIC API (for import) ----------------------------------------

def generate_diff_html(xml_before: str,
                       xml_after: str,
                       output_html: str,
                       device_name: str = "Device",
                       siblings: int = 0):
    """
    Main entry point when calling from another script.
    Accepts XML strings directly.
    """
    blocks = build_context_blocks(xml_before, xml_after, sibling_count=siblings)
    render_blocks_to_html(blocks, output_html, device_name=device_name)
