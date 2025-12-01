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
        Compares two XML strings (Before vs After) and returns a structured diff
        preserving parent hierarchy with inline styling for reporting.
        Unchanged subtrees are pruned from the output.
        """
        
        # Helper for HTML escaping to ensure tags are visible in the report
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
            import difflib
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

        # 3. Custom Serializer (Avoids minidom whitespace issues & handles inline leaves)
        def serialize(elem, level=0):
            if elem is None: return ""
            indent = "  " * level
            
            # Attributes
            attrs = ""
            for k, v in elem.attrib.items():
                if not k.startswith('__'):
                    attrs += ' {}="{}"'.format(k, v)
            
            tag = elem.tag
            style = elem.get('__diff_style__')
            
            # Construct start/end tags TEXT (e.g. <tag>)
            start_tag_text = "<{}{}>".format(tag, attrs)
            end_tag_text = "</{}>".format(tag)
            
            # Escape for HTML display (e.g. &lt;tag&gt;)
            start_tag_html = escape_html(start_tag_text)
            end_tag_html = escape_html(end_tag_text)
            
            if style:
                start_tag_html = '<span style="{}">{}</span>'.format(style, start_tag_html)
                end_tag_html = '<span style="{}">{}</span>'.format(style, end_tag_html)
            
            # Leaf Node (Inline)
            if len(elem) == 0:
                text = elem.text or ""
                # text is already escaped and possibly wrapped in spans in compare_nodes
                return '{}{}{}{}
'.format(indent, start_tag_html, text, end_tag_html)
            
            # Container Node
            out = '{}{}
'.format(indent, start_tag_html)
            if elem.text and elem.text.strip():
                 out += '{}  {}
'.format(indent, elem.text.strip())
            
            for child in elem:
                out += serialize(child, level + 1)
            
            out += '{}{}
'.format(indent, end_tag_html)
            return out
            
        left_out = serialize(result_left).strip()
        right_out = serialize(result_right).strip()

        return {
            "left": left_out if left_out else "<!-- No Changes -->",
            "right": right_out if right_out else "<!-- No Changes -->",
            "metadata": {
                "changed": any_change,
                "added_count": self.stats["added"],
                "removed_count": self.stats["removed"],
                "changed_count": self.stats["modified"]
            }
        }
