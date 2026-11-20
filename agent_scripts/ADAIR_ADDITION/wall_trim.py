"""Pull new wall ends back from an existing wall's centerline to its face.

Where a new wall ends inside an existing wall that runs across it, the end is
moved back along the new wall to the existing wall's near face, and the wall join
at that end is released (otherwise Revit pulls the end back to the centerline).
"""
from pyrevit.api import DB
from System import Int64


def a(x):
    return ''.join(c if ord(c) < 128 else '?' for c in unicode(x or ''))


def flat(p):
    return DB.XYZ(p.X, p.Y, 0)


def crossing_wall(doc, wall, end, candidates):
    """Existing wall running across `wall` whose thickness contains its end."""
    c = wall.Location.Curve
    d = flat(c.GetEndPoint(1) - c.GetEndPoint(0)).Normalize()
    p = flat(c.GetEndPoint(end))
    best = None
    for e in candidates:
        ec = e.Location.Curve
        ed = flat(ec.GetEndPoint(1) - ec.GetEndPoint(0)).Normalize()
        if abs(ed.DotProduct(d)) > 0.1:
            continue
        line = DB.Line.CreateUnbound(flat(ec.GetEndPoint(0)), ed)
        dist = line.Project(p).Distance
        if dist < e.Width / 2.0 + 1e-6 and (best is None or dist < best[1]):
            best = (e, dist)
    return best


def trim(doc, wall_id, end, candidates):
    """Move end of wall to the near face of the crossing existing wall.  Returns
    a summary; call inside a transaction."""
    w = doc.GetElement(DB.ElementId(Int64(wall_id)))
    hit = crossing_wall(doc, w, end, candidates)
    if hit is None:
        return {'wall': wall_id, 'error': 'no crossing existing wall at that end'}
    e, dist = hit
    c = w.Location.Curve
    p_end, p_far = c.GetEndPoint(end), c.GetEndPoint(1 - end)
    back = (p_far - p_end).Normalize()
    ec = e.Location.Curve
    ed = flat(ec.GetEndPoint(1) - ec.GetEndPoint(0)).Normalize()
    n = DB.XYZ(-ed.Y, ed.X, 0)
    side = 1.0 if flat(p_far - ec.GetEndPoint(0)).DotProduct(n) > 0 else -1.0
    signed = flat(p_end - ec.GetEndPoint(0)).DotProduct(n) * side
    move = (e.Width / 2.0 - signed) / abs(back.DotProduct(n))
    new_end = p_end + back * move
    DB.WallUtils.DisallowWallJoinAtEnd(w, end)
    doc.Regenerate()
    w.Location.Curve = DB.Line.CreateBound(p_far, new_end) if end == 1 else DB.Line.CreateBound(new_end, p_far)
    doc.Regenerate()
    q = w.Location.Curve.GetEndPoint(end)
    return {'wall': wall_id, 'existing': [e.Id.Value, a(doc.GetElement(e.GetTypeId()).get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString())],
            'from': [round(p_end.X, 3), round(p_end.Y, 3)], 'to': [round(q.X, 3), round(q.Y, 3)],
            'shortened_in': round(move * 12, 2), 'held': q.DistanceTo(new_end) < 1e-4}
