#!/usr/bin/python
# filter_plugins/xml_struct_diff.py

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import re
import xml.etree.ElementTree as ET
from copy import deepcopy

class FilterModule(object):
    def filters(self):
        return {
            'xml_struct_diff': self.xml_struct_diff
        }

    def xml_struct_diff(self, before_xml, after_xml):
        """
        Compares two XML strings (Before vs After) using a structural merge-join strategy.
        1. Normalizes and removes namespaces.
        2. Canonically sorts elements based on "Identity Keys" (Tags + specific ID children like <name>, <id>).
        3. Compares trees using a merge-join algorithm to correctly handle insertions/removals in lists.
        4. Generates HTML-ready output with inline styles and spacer blocks for synchronized scrolling.
        """
        
        # --- Helpers ---
        
        def escape_html(s):
            if not s: return ""
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        def get_identity_key(node):
            """
            Generates a comparison key for a node.
            Priority: Tag -> Attributes -> ID Child Value -> Text Content
            """
            key_parts = [node.tag]
            
            # Attributes
            if node.attrib:
                key_parts.append(str(sorted(node.attrib.items())))
                
            # Look for Identifying Children (Common in NETCONF)
            # This helps align <vlan> nodes by their <id> even if out of order
            found_id = False
            for k in ['id', 'name', 'key', 'neighbor-address', 'prefix', 'vlan-id']:
                child = node.find(k)
                if child is not None and child.text:
                    key_parts.append(k + ":" + child.text.strip())
                    found_id = True
                    break
            
            # Fallback: Use text content if it's a leaf-like node
            if not found_id:
                txt = (node.text or "").strip()
                if txt:
                    key_parts.append("text:" + txt)
            
            return tuple(key_parts)

        def sort_tree(node):
            """Recursively sorts children by identity key."""
            node[:] = sorted(node, key=get_identity_key)
            for child in node:
                sort_tree(child)

        def count_lines(elem, is_leaf=False):
            """
            Calculates visual height (lines) of an element for spacer generation.
            """
            if elem is None: return 0
            
            # Check for explicitly set spacer lines
            if elem.tag == "__spacer__":
                return int(elem.get('lines', 0))
            
            # Leaf node <tag>val</tag> is 1 line
            if len(elem) == 0:
                return 1
                
            # Container: OpenTag + (Text?) + Children + CloseTag
            lines = 2 
            if elem.text and elem.text.strip():
                lines += 1
                
            for child in elem:
                lines += count_lines(child)
                
            # Add appended spacers
            lines += int(elem.get('__append_spacer__', 0))
            return lines

        # --- Main Logic ---

        def parse_clean(xml_str):
            if not xml_str or not xml_str.strip():
                return None
            # Remove namespaces
            clean_xml = re.sub(r' xmlns="[^"]+"', '', xml_str, count=0)
            clean_xml = re.sub(r' xmlns:[a-z0-9]+="[^"]+"', '', clean_xml, count=0)
            try:
                root = ET.fromstring(clean_xml)
                sort_tree(root)
                return root
            except ET.ParseError:
                return None

        root_before = parse_clean(before_xml)
        root_after = parse_clean(after_xml)

        self.stats = {"added": 0, "removed": 0, "modified": 0}

        def mark_tree(element, style):
            """Recursively marks a tree as added/removed."""
            if element is None: return
            if element.text and element.text.strip():
                element.text = '<span style="{} font-weight:bold;">{}</span>'.format(style, escape_html(element.text))
            
            element.set('__diff_style__', style)
            for child in element:
                mark_tree(child, style)

        def compare_nodes(node_a, node_b):
            # Case 0: Both None
            if node_a is None and node_b is None:
                return (None, None, False)

            # Case 1: Removal (A exists, B is None)
            if node_b is None:
                self.stats["removed"] += 1
                res_a = deepcopy(node_a)
                mark_tree(res_a, "color:#cc0000;") # Red
                lines = count_lines(res_a)
                res_b_spacer = ET.Element("__spacer__", lines=str(lines))
                return (res_a, res_b_spacer, True)

            # Case 2: Addition (A is None, B exists)
            if node_a is None:
                self.stats["added"] += 1
                res_b = deepcopy(node_b)
                mark_tree(res_b, "color:#00aa00;") # Green
                lines = count_lines(res_b)
                res_a_spacer = ET.Element("__spacer__", lines=str(lines))
                return (res_a_spacer, res_b, True)

            # Case 3: Different Tags (treat as remove + add)
            # Note: With identity key sorting, this rarely happens unless key matched but tag differed?
            # Actually, key includes tag, so this block might be unreachable via merge-join, 
            # but safe to keep for root or direct calls.
            if node_a.tag != node_b.tag:
                self.stats["removed"] += 1
                self.stats["added"] += 1
                res_a = deepcopy(node_a)
                res_b = deepcopy(node_b)
                mark_tree(res_a, "color:#cc0000;")
                mark_tree(res_b, "color:#00aa00;")
                
                # Balance lines
                lines_a = count_lines(res_a)
                lines_b = count_lines(res_b)
                max_lines = max(lines_a, lines_b)
                
                if lines_a < max_lines: res_a.set('__append_spacer__', str(max_lines - lines_a))
                if lines_b < max_lines: res_b.set('__append_spacer__', str(max_lines - lines_b))
                    
                return (res_a, res_b, True)

            # Case 4: Same Tag - Compare Internals
            text_a = (node_a.text or "").strip()
            text_b = (node_b.text or "").strip()
            text_changed = text_a != text_b
            
            out_a = ET.Element(node_a.tag, attrib=node_a.attrib)
            out_b = ET.Element(node_b.tag, attrib=node_b.attrib)
            
            has_child_changes = False
            
            # --- Merge-Join Children ---
            children_a = list(node_a) # Sorted
            children_b = list(node_b) # Sorted
            
            idx_a = 0
            idx_b = 0
            len_a = len(children_a)
            len_b = len(children_b)
            
            while idx_a < len_a or idx_b < len_b:
                c_a = children_a[idx_a] if idx_a < len_a else None
                c_b = children_b[idx_b] if idx_b < len_b else None
                
                k_a = get_identity_key(c_a) if c_a is not None else None
                k_b = get_identity_key(c_b) if c_b is not None else None
                
                # Match
                if k_a == k_b:
                    res_child_a, res_child_b, changed = compare_nodes(c_a, c_b)
                    if changed: has_child_changes = True
                    out_a.append(res_child_a)
                    out_b.append(res_child_b)
                    idx_a += 1
                    idx_b += 1
                
                # Removed (A < B or B exhausted)
                elif c_b is None or (c_a is not None and k_a < k_b):
                    res_child_a, res_child_b, changed = compare_nodes(c_a, None)
                    has_child_changes = True
                    out_a.append(res_child_a)
                    out_b.append(res_child_b)
                    idx_a += 1
                    
                # Added (B < A or A exhausted)
                else:
                    res_child_a, res_child_b, changed = compare_nodes(None, c_b)
                    has_child_changes = True
                    out_a.append(res_child_a)
                    out_b.append(res_child_b)
                    idx_b += 1

            # --- Text Content ---
            if text_changed:
                self.stats["modified"] += 1
                out_a.text = '<span style="color:#ff8800; font-weight:bold;">{}</span>'.format(escape_html(text_a))
                out_b.text = '<span style="color:#ff8800; font-weight:bold;">{}</span>'.format(escape_html(text_b))
                out_a.set('__diff_style__', 'color:#ff8800;') 
                out_b.set('__diff_style__', 'color:#ff8800;')
            else:
                out_a.text = escape_html(text_a)
                out_b.text = escape_html(text_b)

            # --- Pruning ---
            if not text_changed and not has_child_changes:
                return (None, None, False)

            # --- Final Balancing (Crucial for Side-by-Side) ---
            l_lines = count_lines(out_a)
            r_lines = count_lines(out_b)
            
            if l_lines < r_lines:
                out_a.set('__append_spacer__', str(r_lines - l_lines))
            elif r_lines < l_lines:
                out_b.set('__append_spacer__', str(l_lines - r_lines))

            return (out_a, out_b, True)

        # Start Comparison
        result_left, result_right, any_change = compare_nodes(root_before, root_after)

        # 4. Serialize to HTML
        def serialize(elem, level=0):
            if elem is None: return ""
            
            # Spacer
            if elem.tag == "__spacer__":
                lines = int(elem.get('lines', 1))
                return "".join(['<div class="spacer">&nbsp;</div>' for _ in range(lines)])

            indent_style = "padding-left: {}px;".format(level * 20)
            
            # Tag Attributes
            attrs = ""
            for k, v in elem.attrib.items():
                if not k.startswith('__'):
                    val = escape_html(v).replace('"', '&quot;')
                    attrs += ' {}="{}"'.format(k, val)
            
            tag = elem.tag
            diff_style = elem.get('__diff_style__')
            tag_style = diff_style if diff_style else "color: #6b7280;"
            
            start_tag_html = '<span style="{}">&lt;{}{}&gt;</span>'.format(tag_style, tag, attrs)
            end_tag_html = '<span style="{}">&lt;/{}&gt;</span>'.format(tag_style, tag)
            
            # Appended Spacers
            append_spacer = int(elem.get('__append_spacer__', 0))
            spacer_html = "".join(['<div class="spacer">&nbsp;</div>' for _ in range(append_spacer)])

            # Leaf Node (Inline)
            if len(elem) == 0:
                text = elem.text or ""
                content_html = text
                if not content_html.startswith('<span'):
                    content_html = '<span style="color: #374151;">{}</span>'.format(content_html)
                
                return '<div style="{}">{}{}{}</div>{}'.format(indent_style, start_tag_html, content_html, end_tag_html, spacer_html)
            
            # Container Node
            out = '<div style="{}">{}</div>'.format(indent_style, start_tag_html)
            
            if elem.text and elem.text.strip():
                text_indent = "padding-left: {}px;".format((level * 20) + 20)
                text_content = elem.text.strip()
                if not text_content.startswith('<span'):
                    text_content = '<span style="color: #374151;">{}</span>'.format(text_content)
                out += '<div style="{}">{}</div>'.format(text_indent, text_content)
                
            for child in elem:
                out += serialize(child, level + 1)
                
            out += '<div style="{}">{}</div>'.format(indent_style, end_tag_html)
            out += spacer_html
            return out
            
        left_out = serialize(result_left)
        right_out = serialize(result_right)

        return {
            "left": left_out if left_out else '<div class="text-gray-400 italic p-4">No Changes</div>',
            "right": right_out if right_out else '<div class="text-gray-400 italic p-4">No Changes</div>',
            "metadata": {
                "changed": any_change,
                "added_count": self.stats["added"],
                "removed_count": self.stats["removed"],
                "changed_count": self.stats["modified"]
            }
        }
