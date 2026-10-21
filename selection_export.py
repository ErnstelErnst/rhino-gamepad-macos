"""Selection metadata exports only; no geometry picking or display conduit."""
import json
import os
import tempfile
import time
import Rhino.Geometry as rg
EXPORT_DIR = os.path.expanduser('~/Documents/RhinoGamepad')

def _safe_selected_components(obj):
    try:
        return list(obj.GetSelectedSubObjects() or [])
    except Exception:
        return []


def describe_selection(doc):
    """Small explicit metadata snapshot; never contains file path or full mesh."""
    result = {"schema_version": 1, "source": "Rhino 8 Gamepad v0.3.2",
              "created_local": time.strftime('%Y-%m-%dT%H:%M:%S'),
              "units": str(doc.ModelUnitSystem), "objects": []}
    seen = set()
    for obj in doc.Objects.GetSelectedObjects(False, False):
        if str(obj.Id) in seen:
            continue
        seen.add(str(obj.Id))
        geo = obj.Geometry
        if geo is None:
            continue
        box = geo.GetBoundingBox(False)
        try:
            layer = doc.Layers[obj.Attributes.LayerIndex].FullPath
        except Exception:
            layer = ''
        item = {"id": str(obj.Id), "type": type(geo).__name__,
                "name": str(obj.Name or ''), "layer": str(layer),
                "selected_components": [{"type": str(ci.ComponentIndexType), "index": int(ci.Index)}
                                        for ci in _safe_selected_components(obj)]}
        if box.IsValid:
            item["bounding_box"] = {"min": [box.Min.X, box.Min.Y, box.Min.Z],
                                    "max": [box.Max.X, box.Max.Y, box.Max.Z]}
        if isinstance(geo, rg.Curve):
            try:
                item["curve_length"] = float(geo.GetLength())
            except Exception:
                pass
        elif isinstance(geo, rg.Brep):
            item["brep_face_count"] = int(geo.Faces.Count)
            item["brep_edge_count"] = int(geo.Edges.Count)
        result["objects"].append(item)
    return result


def export_context(doc, path=None):
    data = describe_selection(doc)
    if not data['objects']:
        return None, 0
    output = path or os.path.join(EXPORT_DIR, 'selection_context.json')
    os.makedirs(os.path.dirname(output), exist_ok=True)
    # Keep only latest selected context; never write network or CAD geometry.
    temp = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=os.path.dirname(output),
                                         prefix='.selection_', suffix='.json', delete=False) as stream:
            temp = stream.name
            json.dump(data, stream, ensure_ascii=False, indent=2)
        os.replace(temp, output)
    finally:
        if temp and os.path.exists(temp):
            os.unlink(temp)
    return output, len(data['objects'])


def agent_prompt(doc):
    """Produce a text context that can be copied to a separate agent voluntarily."""
    data = describe_selection(doc)
    lines = [
        '# Rhino selection context', '',
        'I selected the following geometry in Rhino 8 using a gamepad.',
        'The data are metadata, not a copy of the 3D model.',
        'You do NOT have access to Rhino or geometry unless I provide it separately.',
        'Please discuss the selected items by their identifiers and ask before changing geometry.',
        '', 'Model units: {}'.format(data['units']), '',
    ]
    for item in data['objects']:
        lines.append('- {} ({}) | {} | layer: {} | ID: {}'.format(
            item['name'] or 'Unnamed', item['type'],
            ', '.join('{}#{}'.format(c['type'], c['index']) for c in item['selected_components']) or 'whole object',
            item['layer'], item['id']))
    lines.extend(['', 'Question / proposed action:', ''])
    return '\n'.join(lines)


def export_with_prompt(doc):
    """Write the JSON and a readable agent handoff file, only on explicit Y."""
    path, count = export_context(doc)
    if not path:
        return None, None, 0
    second = os.path.join(os.path.dirname(path), 'selection_for_agent.md')
    with open(second, 'w', encoding='utf-8') as f:
        f.write(agent_prompt(doc))
    return path, second, count

# v0.5: The basket is the authoritative sharing scope, NOT Rhino's global selection.
# Legacy export_with_prompt remains available for older integrations, but the v0.5
# Y button uses only export_basket_with_prompt.

def describe_basket(doc, entries):
    """Describe exact basket identities, not any unrelated Rhino selections."""
    seen, items, grouped = set(), [], {}
    for entry in entries:
        kind = str(entry.get('kind', 'object'))
        index = int(entry.get('index', -1))
        ident = (str(entry.get('id', '')), kind, index)
        if ident in seen or kind not in ('object', 'face', 'edge', 'curve'):
            continue
        seen.add(ident)
        obj = doc.Objects.FindId(entry.get('guid'))
        if obj is None or obj.Geometry is None:
            continue  # deleted objects are not exported as though they still exist
        geo = obj.Geometry
        # Stale subobject indices must not be represented as valid geometry.
        # Topology-changing commands can invalidate previously collected faces.
        if kind in ('face', 'edge'):
            if not isinstance(geo, rg.Brep):
                continue
            try:
                component_count = geo.Faces.Count if kind == 'face' else geo.Edges.Count
                if index < 0 or index >= component_count:
                    continue
            except Exception:
                continue
        try:
            layer = str(doc.Layers[obj.Attributes.LayerIndex].FullPath)
        except Exception:
            layer = ''
        item = {'id': str(obj.Id), 'name': str(obj.Name or ''),
                'kind': kind, 'index': index, 'layer': layer,
                'geometry_type': type(geo).__name__,
                'approximate_pick': bool(entry.get('approx', False))}
        try:
            component = geo
            if isinstance(geo, rg.Brep):
                if kind == 'face' and 0 <= index < geo.Faces.Count:
                    component = geo.Faces[index]
                elif kind == 'edge' and 0 <= index < geo.Edges.Count:
                    component = geo.Edges[index]
            bbox = component.GetBoundingBox(False)
            if bbox.IsValid:
                item['bounding_box'] = {
                    'min': [float(bbox.Min.X), float(bbox.Min.Y), float(bbox.Min.Z)],
                    'max': [float(bbox.Max.X), float(bbox.Max.Y), float(bbox.Max.Z)]}
        except Exception:
            pass
        items.append(item)
        # Same objects[] compatibility grouping as v0.3 for tools expecting it.
        if item['id'] not in grouped:
            grouped[item['id']] = {'id': item['id'], 'name': item['name'],
                                   'type': item['geometry_type'], 'layer': item['layer'],
                                   'selected_components': []}
        if kind in ('face', 'edge'):
            grouped[item['id']]['selected_components'].append({'type': kind, 'index': index})
        else:
            grouped[item['id']]['whole_object_in_basket'] = True
    return {'schema_version': 2, 'source': 'Rhino Gamepad v0.5 selection basket',
            'created_local': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'units': str(doc.ModelUnitSystem),
            'basket_count': len(items), 'selection_items': items,
            'objects': list(grouped.values()),
            'handoff': 'local_files_and_optional_clipboard_only'}


def basket_prompt(data):
    lines = [
        '# Rhino selection basket for agent', '',
        'These are the exact elements I collected using the gamepad in Rhino 8.',
        'Use their Rhino object IDs and subobject indices as references.',
        'If you have a live RhinoAI/MCP connection, resolve IDs there before making claims about geometry.',
        'This text is only a metadata snapshot; no geometry or 3DM file is attached.',
        'Do not change my model without asking me first.',
        '', 'Units: {}'.format(data['units']),
        'Basket: {} elements'.format(data['basket_count']), ''
    ]
    for i, item in enumerate(data['selection_items'], 1):
        lines.append('{}. {} | {} #{} | object ID: {} | layer: {}'.format(
            i, item['name'] or 'Unnamed', item['kind'], item['index'],
            item['id'], item['layer']))
    lines.extend(['', 'My question / requested action:', ''])
    return '\n'.join(lines)


def _atomic_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8',
                                         dir=os.path.dirname(path), prefix='.basket_',
                                         suffix='.tmp', delete=False) as stream:
            temp = stream.name
            stream.write(text)
        os.replace(temp, path)
    finally:
        if temp and os.path.exists(temp):
            os.unlink(temp)


def copy_for_agent(text):
    """Mac-only best effort. Runs only on explicit Y. Does NOT contact an agent."""
    import subprocess
    try:
        result = subprocess.run(['pbcopy'], input=text, text=True,
                                capture_output=True, timeout=1.5, check=False)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def export_basket_with_prompt(doc, entries, folder=None, copy_clipboard=True):
    data = describe_basket(doc, entries)
    if not data['selection_items']:
        return None, None, 0, False
    folder = folder or EXPORT_DIR
    jsonpath = os.path.join(folder, 'selection_context.json')
    mdpath = os.path.join(folder, 'selection_for_agent.md')
    prompt = basket_prompt(data)
    _atomic_text(jsonpath, json.dumps(data, ensure_ascii=False, indent=2))
    _atomic_text(mdpath, prompt)
    copied = copy_for_agent(prompt) if copy_clipboard else False
    return jsonpath, mdpath, len(data['selection_items']), copied
