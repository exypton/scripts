#!/usr/bin/python
# filter_plugins/xml_struct_diff.py

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import re
import xml.etree.ElementTree as ET
import difflib
from copy import deepcopy

class FilterModule(object):
    def filters(self):
        return {
            'xml_struct_diff': self.xml_struct_diff
        }

    def xml_struct_diff(self, before_xml, after_xml):
        """
        Compares two XML strings (Before vs After) and returns a structured diff
        preserving parent hierarchy with inline styling for reporting.
        Unchanged subtrees are pruned from the output.
        Ignores moved elements by canonically sorting the XML tree.
        """
        
        # Helper for HTML escaping
        def escape_html(s):
            if not s: return ""
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        # Recursive Sorter to ignore moves
        def sort_tree(node):
            # Sort children by Tag, then Attributes, then Text
            node[:] = sorted(node, key=lambda child: (
                child.tag, 
                sorted(child.attrib.items()), 
                (child.text or "").strip()
            ))
            for child in node:
                sort_tree(child)

        # 1. Normalize and Parse
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

        # Counters
        self.stats = {
            "added": 0,
            "removed": 0,
            "modified": 0
        }

        # Helper to calculate rendered line count for spacers
        def count_lines(elem, is_leaf=False):
            if elem is None: return 0
            if is_leaf: return 1 # <tag>value</tag> is 1 line
            
            # Open tag (1) + Text content (0 or 1) + Children + Close tag (1)
            lines = 2 
            if elem.text and elem.text.strip():
                lines += 1
            for child in elem:
                # Check if child is leaf
                child_is_leaf = (len(child) == 0)
                lines += count_lines(child, child_is_leaf)
            return lines

        # 2. Recursive Comparison
        
        def compare_nodes(node_a, node_b):
            if node_a is None and node_b is None:
                return (None, None, False)

            # Node Removed
            if node_b is None:
                self.stats["removed"] += 1
                res_a = deepcopy(node_a)
                mark_tree(res_a, "color:#cc0000;") # Red
                # Count lines for spacer
                lines = count_lines(res_a, len(res_a) == 0)
                res_b_spacer = ET.Element("__spacer__", lines=str(lines))
                return (res_a, res_b_spacer, True)

            # Node Added
            if node_a is None:
                self.stats["added"] += 1
                res_b = deepcopy(node_b)
                mark_tree(res_b, "color:#00aa00;") # Green
                lines = count_lines(res_b, len(res_b) == 0)
                res_a_spacer = ET.Element("__spacer__", lines=str(lines))
                return (res_a_spacer, res_b, True)

            # Compare Tags (Since we sorted, mismatch usually means total difference)
            if node_a.tag != node_b.tag:
                self.stats["removed"] += 1
                self.stats["added"] += 1
                res_a = deepcopy(node_a)
                res_b = deepcopy(node_b)
                mark_tree(res_a, "color:#cc0000;")
                mark_tree(res_b, "color:#00aa00;")
                
                # Balance lines
                lines_a = count_lines(res_a, len(res_a)==0)
                lines_b = count_lines(res_b, len(res_b)==0)
                
                if lines_a < lines_b:
                    res_a.set('__append_spacer__', str(lines_b - lines_a))
                elif lines_b < lines_a:
                    res_b.set('__append_spacer__', str(lines_a - lines_b))
                    
                return (res_a, res_b, True)

            # Compare Attributes & Text
            text_a = (node_a.text or "").strip()
            text_b = (node_b.text or "").strip()
            is_modified = text_a != text_b
            
            if node_a.attrib != node_b.attrib:
                is_modified = True

            out_a = ET.Element(node_a.tag, attrib=node_a.attrib)
            out_b = ET.Element(node_b.tag, attrib=node_b.attrib)
            
            children_a = list(node_a)
            children_b = list(node_b)
            
            # Since sorted, we iterate in lockstep
            # Note: This is a simplified diff for sorted trees. 
            # A more complex Myers diff could be used here if inserts cause massive shifts,
            # but for config normalization, sorted alignment is usually sufficient.
            
            has_child_changes = False
            max_len = max(len(children_a), len(children_b))
            
            for i in range(max_len):
                c_a = children_a[i] if i < len(children_a) else None
                c_b = children_b[i] if i < len(children_b) else None
                
                child_res_a, child_res_b, changed = compare_nodes(c_a, c_b)
                if changed:
                    has_child_changes = True
                    out_a.append(child_res_a)
                    out_b.append(child_res_b)

            # Text content check
            if is_modified:
                self.stats["modified"] += 1
                # Mark text specifically. Escape first, then wrap.
                out_a.text = '<span style="color:#ff8800; font-weight:bold;">{}</span>'.format(escape_html(text_a))
                out_b.text = '<span style="color:#ff8800; font-weight:bold;">{}</span>'.format(escape_html(text_b))
                out_a.set('__diff_style__', 'color:#ff8800;') 
                out_b.set('__diff_style__', 'color:#ff8800;')
            else:
                out_a.text = escape_html(text_a)
                out_b.text = escape_html(text_b)
            
            # PRUNING: If no text change and no child changes, return Nothing
            if not is_modified and not has_child_changes:
                return (None, None, False)
                
            return (out_a, out_b, True)

        def mark_tree(element, style):
            if element is None: return
            if element.text and element.text.strip():
                element.text = '<span style="{} font-weight:bold;">{}</span>'.format(style, escape_html(element.text))
            
            element.set('__diff_style__', style)
            for child in element:
                mark_tree(child, style)

        result_left, result_right, any_change = compare_nodes(root_before, root_after)

        # 3. Custom Serializer
        def serialize(elem, level=0):
            if elem is None: return ""
            
            # Handle Spacer Nodes
            if elem.tag == "__spacer__":
                lines = int(elem.get('lines', 1))
                return "".join(['<div class="spacer">&nbsp;</div>' for _ in range(lines)])

            indent_style = "padding-left: {}px;".format(level * 20)
            
            # Attributes
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
            
            # Check for appended spacers (for balancing mismatched blocks)
            append_spacer = int(elem.get('__append_spacer__', 0))
            spacer_html = "".join(['<div class="spacer">&nbsp;</div>' for _ in range(append_spacer)])

            # LEAF NODE (Inline)
            if len(elem) == 0:
                text = elem.text or ""
                content_html = text
                if not content_html.startswith('<span'):
                    content_html = '<span style="color: #374151;">{}</span>'.format(content_html)
                
                # Corrected format string (4 args)
                return '<div style="{}">{}{}{}</div>{}'.format(indent_style, start_tag_html, content_html, end_tag_html, spacer_html)
            
            # CONTAINER NODE
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
