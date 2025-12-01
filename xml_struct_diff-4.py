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
        Returns HTML strings (using div blocks) ready for insertion into a report.
        """
        
        # Helper for HTML escaping
        def escape_html(s):
            if not s: return ""
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        # 1. Normalize and Parse
        def parse_clean(xml_str):
            if not xml_str or not xml_str.strip():
                return None
            # Remove namespaces
            clean_xml = re.sub(r' xmlns="[^"]+"', '', xml_str, count=0)
            clean_xml = re.sub(r' xmlns:[a-z0-9]+="[^"]+"', '', clean_xml, count=0)
            try:
                return ET.fromstring(clean_xml)
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

        # 2. Recursive Comparison
        
        def compare_nodes(node_a, node_b):
            if node_a is None and node_b is None:
                return (None, None, False)

            # Node Removed
            if node_b is None:
                self.stats["removed"] += 1
                res_a = deepcopy(node_a)
                mark_tree(res_a, "color:#cc0000;") # Red
                return (res_a, None, True)

            # Node Added
            if node_a is None:
                self.stats["added"] += 1
                res_b = deepcopy(node_b)
                mark_tree(res_b, "color:#00aa00;") # Green
                return (None, res_b, True)

            # Compare Tags
            if node_a.tag != node_b.tag:
                self.stats["removed"] += 1
                self.stats["added"] += 1
                res_a = deepcopy(node_a)
                res_b = deepcopy(node_b)
                mark_tree(res_a, "color:#cc0000;")
                mark_tree(res_b, "color:#00aa00;")
                return (res_a, res_b, True)

            # Compare Attributes & Text
            text_a = (node_a.text or "").strip()
            text_b = (node_b.text or "").strip()
            is_modified = text_a != text_b
            
            # Simple attribute check
            if node_a.attrib != node_b.attrib:
                is_modified = True

            out_a = ET.Element(node_a.tag, attrib=node_a.attrib)
            out_b = ET.Element(node_b.tag, attrib=node_b.attrib)
            
            children_a = list(node_a)
            children_b = list(node_b)
            
            # Map children by tags to find sequence matches
            s = difflib.SequenceMatcher(None, [c.tag for c in children_a], [c.tag for c in children_b])
            
            has_child_changes = False

            for tag, i1, i2, j1, j2 in s.get_opcodes():
                if tag == 'equal':
                    for k in range(i2-i1):
                        child_res_a, child_res_b, changed = compare_nodes(children_a[i1+k], children_b[j1+k])
                        if changed:
                            has_child_changes = True
                            out_a.append(child_res_a)
                            out_b.append(child_res_b)
                elif tag == 'replace':
                    has_child_changes = True
                    for c in children_a[i1:i2]:
                        r_a, _, _ = compare_nodes(c, None)
                        out_a.append(r_a)
                    for c in children_b[j1:j2]:
                        _, r_b, _ = compare_nodes(None, c)
                        out_b.append(r_b)
                elif tag == 'delete':
                    has_child_changes = True
                    for c in children_a[i1:i2]:
                        r_a, _, _ = compare_nodes(c, None)
                        out_a.append(r_a)
                elif tag == 'insert':
                    has_child_changes = True
                    for c in children_b[j1:j2]:
                        _, r_b, _ = compare_nodes(None, c)
                        out_b.append(r_b)

            # Text content check
            if is_modified:
                self.stats["modified"] += 1
                # Mark text specifically. Escape first, then wrap.
                out_a.text = '<span style="color:#ff8800; font-weight:bold;">{}</span>'.format(escape_html(text_a))
                out_b.text = '<span style="color:#ff8800; font-weight:bold;">{}</span>'.format(escape_html(text_b))
                # Also mark tag slightly to indicate change inside
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
                # Escape existing text, then wrap
                element.text = '<span style="{} font-weight:bold;">{}</span>'.format(style, escape_html(element.text))
            
            element.set('__diff_style__', style)
            for child in element:
                mark_tree(child, style)

        result_left, result_right, any_change = compare_nodes(root_before, root_after)

        # 3. Custom Serializer (Produces HTML structure with inline styles)
        # We use <div> blocks with padding for indentation to ensure the report renders 
        # correctly regardless of CSS whitespace settings.
        def serialize(elem, level=0):
            if elem is None: return ""
            
            # Using 20px per level indentation
            indent_style = "padding-left: {}px;".format(level * 20)
            
            # Attributes
            attrs = ""
            for k, v in elem.attrib.items():
                if not k.startswith('__'):
                    # Basic escape for attribute values
                    val = escape_html(v).replace('"', '&quot;')
                    attrs += ' {}="{}"'.format(k, val)
            
            tag = elem.tag
            diff_style = elem.get('__diff_style__')
            
            # Tag Style (Default Gray if not changed)
            tag_style = diff_style if diff_style else "color: #6b7280;"
            
            start_tag_html = '<span style="{}">&lt;{}{}&gt;</span>'.format(tag_style, tag, attrs)
            end_tag_html = '<span style="{}">&lt;/{}&gt;</span>'.format(tag_style, tag)
            
            # LEAF NODE (Inline)
            if len(elem) == 0:
                text = elem.text or ""
                # Text coloring is handled in compare_nodes by wrapping in span.
                # If raw text (unchanged), wrap in default color
                content_html = text
                if not content_html.startswith('<span'):
                    content_html = '<span style="color: #374151;">{}</span>'.format(content_html)
                
                # Corrected format string to include all 4 arguments (was missing one {})
                return '<div style="{}">{}{}{}</div>'.format(indent_style, start_tag_html, content_html, end_tag_html)
            
            # CONTAINER NODE
            # Open Tag
            out = '<div style="{}">{}</div>'.format(indent_style, start_tag_html)
            
            if elem.text and elem.text.strip():
                # Text content in container (indented further)
                text_indent = "padding-left: {}px;".format((level * 20) + 20)
                text_content = elem.text.strip()
                if not text_content.startswith('<span'):
                    text_content = '<span style="color: #374151;">{}</span>'.format(text_content)
                out += '<div style="{}">{}</div>'.format(text_indent, text_content)
                
            for child in elem:
                out += serialize(child, level + 1)
                
            out += '<div style="{}">{}</div>'.format(indent_style, end_tag_html)
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
