"""Native Brep connectivity-based selection; no meshing or full-scene scans.

D-pad up from face/edge -> incident/adjacent faces.
D-pad down from face/edge -> boundary/shared-face edges.
The adjacency relationship is REAL topology, NOT spatial arrow direction.
"""


def neighbor_indices(brep, kind, index, direction):
    """Return [(kind,index)] for one anchored Brep face/edge.

    Kept independent of Rhino imports for headless mock testing.
    """
    if direction not in ('up', 'down') or not isinstance(index, int) or index < 0:
        return []
    try:
        if kind == 'face' and index < brep.Faces.Count:
            face = brep.Faces[index]
            next_kind = 'face' if direction == 'up' else 'edge'
            indices = face.AdjacentFaces() if direction == 'up' else face.AdjacentEdges()
        elif kind == 'edge' and index < brep.Edges.Count:
            edge = brep.Edges[index]
            if direction == 'up':
                next_kind = 'face'
                indices = edge.AdjacentFaces()
            else:
                # Edges used by any face incident to this edge; this does NOT
                # claim continuous edge-loop/vertex-adjacency semantics.
                next_kind = 'edge'
                faces = edge.AdjacentFaces()
                indices = [i for face_id in faces for i in brep.Faces[face_id].AdjacentEdges()]
        else:
            return []
        return [(next_kind, i) for i in sorted({int(v) for v in indices})
                if i >= 0 and not (next_kind == kind and i == index)]
    except (IndexError, AttributeError, TypeError, ValueError):
        return []


def deduplicate(entries):
    found, seen = [], set()
    for entry in entries:
        key = (entry['id'], entry['kind'], entry['index'])
        if key not in seen:
            seen.add(key)
            found.append(entry)
    return found


# Whole-Brep picking frequently returns an object rather than a face in Ghosted
# mode. Guess possible face anchors using ONLY that object's face bounding boxes;
# never mesh or walk the document. This is not occlusion-accurate ray picking.
def face_anchors_near_cursor(brep, vp, x, y, tolerance_px=16, limit=20):
    """Return candidate face indices near a viewport-local point (approximate).

    Each face is checked once using its 3D bounding box projected onto screen.
    The smallest normalized distance to its projected center sorts candidates;
    a bounding box may span empty trimmed space, so highlight is authoritative.
    """
    import math

    choices = []
    try:
        count = int(brep.Faces.Count)
    except (AttributeError, TypeError, ValueError):
        return []
    # On large imported Breps, keep this single-button action bounded.
    for i in range(min(count, 800)):
        try:
            bounds = brep.Faces[i].GetBoundingBox(True)
            if not bounds.IsValid:
                continue
            pts = [vp.WorldToClient(corner) for corner in bounds.GetCorners()]
            if not pts:
                continue
            xs = [float(p.X) for p in pts]
            ys = [float(p.Y) for p in pts]
            if not all(math.isfinite(v) for v in xs + ys):
                continue
            xmin, xmax = min(xs), max(xs)
            ymin, ymax = min(ys), max(ys)
            if not (xmin - tolerance_px <= x <= xmax + tolerance_px and
                    ymin - tolerance_px <= y <= ymax + tolerance_px):
                continue
            midx, midy = (xmin + xmax) / 2, (ymin + ymax) / 2
            diag = max(1.0, math.hypot(xmax - xmin, ymax - ymin))
            score = math.hypot(x - midx, y - midy) / diag
            choices.append((score, i))
        except (AttributeError, TypeError, ValueError, OverflowError, RuntimeError):
            continue
    choices.sort(key=lambda pair: (pair[0], pair[1]))
    return [i for _, i in choices[:limit]]
