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


# ================================================================
# Utility helpers
# ================================================================

def qname_local(tag):
    """For namespaced tags, return only the local part."""
    if tag is None:
        return ""
    if isinstance(tag, etree.QName):
        return tag.localname
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def pretty_lines_of_element(elem: etree._Element) -> List[str]:
    s = etree.tostring(elem, pretty_print=True, encoding="unicode")
    return s.splitlines()


def open_tag_line(elem: etree._Element, depth: int) -> str:
    tag = qname_local(elem.tag)
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
    """Wrap inner lines with their ancestor tag structure."""
    lines = []

    # open ancestors
    for depth, anc in enumerate(path_elems):
        lines.append(open_tag_line(anc, depth))

    # indent inner content
    indent = "  " * len(path_elems)
    for ln in inner_lines:
        lines.append(indent + ln)

    # close ancestors
    for depth, anc in enumerate(reversed(path_elems)):
        lines.append(close_tag_line(anc, len(path_elems) - depth - 1))

    return lines


def find_child_slice(parent: etree._Element,
                     target: etree._Element,
                     sibling_count: int):
    """Return list of surrounding children including the target."""
    children = [c for c in parent if isinstance(c.tag, str)]

    # find index
    idx = None
    for i, c in enumerate(children):
        if c is target:
            idx = i
            break
        if etree.tostring(c) == etree.tostring(target):
            idx = i
            break

    if idx is None:
        return [target]

    lo = max(0, idx - sibling_count)
    hi = min(len(children) - 1, idx + sibling_count)
    return children[lo : hi + 1]


# ================================================================
# Core diff block builder
# ================================================================

def build_context_blocks(xml_before: str,
                         xml_after: str,
                         sibling_count: int = 0) -> List[Tuple[List[str], List[str]]]:

    # XmlDiffFormatter → list of Action objects
    diff_actions = main.diff_texts(
        xml_before,
        xml_after,
        formatter=formatting.XmlDiffFormatter()
    )

    root_before = etree.fromstring(xml_before)
    root_after = etree.fromstring(xml_after)

    blocks = []
    seen = set()

    for action in diff_actions:
        action_type = type(action).__name__  # e.g. InsertNode, DeleteNode, UpdateText
        node_path = action.node              # xpath string

        key = (action_type, node_path)
        if key in seen:
            continue
        seen.add(key)

        left_block = []
        right_block = []

        # ------------------------------------------------------------
        # DELETE
        # ------------------------------------------------------------
        if action_type == "DeleteNode":
            nodes = root_before.xpath(node_path)
            if nodes:
                target = nodes[0]
                parent = target.getparent()
                ancestors = []
                a = parent
                while a is not None:
                    ancestors.insert(0, a)
                    a = a.getparent()

                slice_children = find_child_slice(parent, target, sibling_count)
                inner = []
                for c in slice_children:
                    inner.extend(pretty_lines_of_element(c))

                left_block = minimal_wrapper_for(ancestors, inner)
                right_block = [""] * len(left_block)

            else:
                left_block = [f"<!-- deleted {node_path} -->"]
                right_block = [""]

        # ------------------------------------------------------------
        # INSERT
        # ------------------------------------------------------------
        elif action_type == "InsertNode":
            nodes = root_after.xpath(node_path)
            if nodes:
                target = nodes[0]
                parent = target.getparent()
                ancestors = []
                a = parent
                while a is not None:
                    ancestors.insert(0, a)
                    a = a.getparent()

                slice_children = find_child_slice(parent, target, sibling_count)
                inner = []
                for c in slice_children:
                    inner.extend(pretty_lines_of_element(c))

                right_block = minimal_wrapper_for(ancestors, inner)
                left_block = [""] * len(right_block)

            else:
                left_block = [""]
                right_block = [f"<!-- inserted {node_path} -->"]

        # ------------------------------------------------------------
        # UPDATE TEXT / UPDATE ATTRIB
        # ------------------------------------------------------------
        elif action_type in ("UpdateText", "UpdateAttrib"):

            # find nodes on both trees
            before_nodes = root_before.xpath(node_path)
            after_nodes = root_after.xpath(node_path)

            parent = None
            if before_nodes:
                parent = before_nodes[0].getparent()
            elif after_nodes:
                parent = after_nodes[0].getparent()

            if not parent:
                left_block = [str(getattr(action, "old", ""))]
                right_block = [str(getattr(action, "new", ""))]
            else:
                ancestors = []
                a = parent
                while a is not None:
                    ancestors.insert(0, a)
                    a = a.getparent()

                # before side
                inner_before = []
                if before_nodes:
                    target_b = before_nodes[0]
                    slice_b = find_child_slice(parent, target_b, sibling_count)
                    for c in slice_b:
                        inner_before.extend(pretty_lines_of_element(c))

                # after side
                inner_after = []
                if after_nodes:
                    target_a = after_nodes[0]
                    slice_a = find_child_slice(parent, target_a, sibling_count)
                    for c in slice_a:
                        inner_after.extend(pretty_lines_of_element(c))

                left_block = minimal_wrapper_for(ancestors, inner_before or [""])
                right_block = minimal_wrapper_for(ancestors, inner_after or [""])

                # pad to equal length
                if len(left_block) < len(right_block):
                    left_block.extend([""] * (len(right_block) - len(left_block)))
                elif len(right_block) < len(left_block):
                    right_block.extend([""] * (len(left_block) - len(right_block)))

        # ------------------------------------------------------------
        # UNKNOWN ACTION
        # ------------------------------------------------------------
        else:
            left_block = [f"<!-- unhandled action {action_type} -->"]
            right_block = [""]

        blocks.append((left_block, right_block))

    return blocks


# ================================================================
# Rendering to HtmlDiff
# ================================================================

def render_blocks_to_html(blocks: List[Tuple[List[str], List[str]]],
                          output_html: str,
                          device_name: str):

    left_lines = []
    right_lines = []
    sep = ["..."]

    for i, (lb, rb) in enumerate(blocks):
        if i > 0:
            left_lines.extend(sep)
            right_lines.extend(sep)
        left_lines.extend(lb)
        right_lines.extend(rb)

    if not left_lines:
        left_lines = ["<!-- no changes -->"]
        right_lines = ["<!-- no changes -->"]

    diff_html = difflib.HtmlDiff(wrapcolumn=120).make_file(
        left_lines,
        right_lines,
        fromdesc=f"Current Configuration ({device_name})",
        todesc=f"Candidate Configuration ({device_name})",
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
