"""Keep the 2x8 sill plate X (Nominal Cut Lumber-Section : 2x8 FLAT detail
component) in step with every section that cuts a FOUNDATION WALLS (NEW) wall.

X's this tool manages carry the comment AUTO SILL X.  An untagged X sitting on a
target is adopted (tagged); other untagged X's are left alone.
"""
from Autodesk.Revit import DB

WALL_TYPE = 'FOUNDATION WALLS (NEW)'
DETAIL_FAMILY, DETAIL_TYPE = 'Nominal Cut Lumber-Section', '2x8 FLAT'
TAG = 'AUTO SILL X'
SILL_W = 7.25 / 12
SQUARE_TOL = 0.98
SAME_TOL = 0.05
SECTION_TYPES = (DB.ViewType.Section, DB.ViewType.Detail)


def tname(e):
    p = e.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
    return p.AsString() if p else None


def comment(e):
    p = e.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    return (p.AsString() or '') if p else ''


def set_comment(e, text):
    e.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).Set(text)


def wall_type_id(doc):
    for t in DB.FilteredElementCollector(doc).OfClass(DB.WallType):
        if tname(t) == WALL_TYPE:
            return t.Id
    return None


def detail_symbol(doc):
    for s in DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol).OfCategory(
            DB.BuiltInCategory.OST_DetailComponents):
        if s.FamilyName == DETAIL_FAMILY and tname(s) == DETAIL_TYPE:
            return s
    return None


def is_section(view):
    return (view is not None and isinstance(view, DB.ViewSection)
            and not view.IsTemplate and view.ViewType in SECTION_TYPES)


def section_views(doc):
    return [v for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewSection) if is_section(v)]


def wall_top_at(wall, p):
    """Top of the wall solid on a vertical line through plan point p."""
    line = DB.Line.CreateBound(DB.XYZ(p.X, p.Y, p.Z - 50.0), DB.XYZ(p.X, p.Y, p.Z + 50.0))
    best = None
    for g in wall.get_Geometry(DB.Options()):
        if isinstance(g, DB.Solid) and g.Volume > 0:
            res = g.IntersectWithCurve(line, DB.SolidCurveIntersectionOptions())
            for k in range(res.SegmentCount):
                z = res.GetCurveSegment(k).GetEndPoint(1).Z
                best = z if best is None else max(best, z)
    return best


def targets(doc, view, wt_id):
    """Insertion points (detail bottom-left corner) for every square cut of the
    wall type inside the view's crop."""
    out = []
    origin, normal = view.Origin, view.ViewDirection
    crop = view.CropBox
    inv = crop.Transform.Inverse
    for w in DB.FilteredElementCollector(doc, view.Id).OfClass(DB.Wall):
        if w.GetTypeId() != wt_id or not isinstance(w.Location, DB.LocationCurve):
            continue
        c = w.Location.Curve
        if not isinstance(c, DB.Line):
            continue
        p0, p1 = c.GetEndPoint(0), c.GetEndPoint(1)
        d0, d1 = (p0 - origin).DotProduct(normal), (p1 - origin).DotProduct(normal)
        if d0 * d1 > 0 or abs(d0 - d1) < 1e-9:
            continue
        if abs((p1 - p0).Normalize().DotProduct(normal)) < SQUARE_TOL:
            continue
        p = p0 + (p1 - p0) * (d0 / (d0 - d1))
        if view.CropBoxActive:
            x = inv.OfPoint(p).X
            if not (crop.Min.X - 1e-3 <= x <= crop.Max.X + 1e-3):
                continue
        top = wall_top_at(w, p)
        if top is not None:
            out.append(DB.XYZ(p.X, p.Y, top) - view.RightDirection * (SILL_W / 2.0))
    return out


def existing(doc, view, sym):
    return [e for e in DB.FilteredElementCollector(doc, view.Id).OfClass(DB.FamilyInstance)
            if e.Symbol.Id == sym.Id and e.OwnerViewId == view.Id]


def plan(doc, view, sym, wt_id):
    """Actions needed to bring one view in step: (kind, instance, point) with kind
    in adopt / add / move / delete.  Reads only."""
    pts = targets(doc, view, wt_id)
    insts = existing(doc, view, sym)
    tagged = [e for e in insts if comment(e) == TAG]
    untagged = [e for e in insts if comment(e) != TAG]
    actions, todo = [], []
    for p in pts:
        hit = [e for e in tagged if e.Location.Point.DistanceTo(p) < SAME_TOL]
        if hit:
            tagged.remove(hit[0])
            continue
        hit = [e for e in untagged if e.Location.Point.DistanceTo(p) < SAME_TOL]
        if hit:
            untagged.remove(hit[0])
            actions.append(('adopt', hit[0], p))
            continue
        todo.append(p)
    for p in todo:
        if tagged:
            e = min(tagged, key=lambda i: i.Location.Point.DistanceTo(p))
            tagged.remove(e)
            actions.append(('move', e, p))
        else:
            actions.append(('add', None, p))
    for e in tagged:
        actions.append(('delete', e, None))
    return actions


def apply(doc, view, sym, actions):
    """Carry out plan() actions; call inside an open transaction."""
    for kind, e, p in actions:
        if kind == 'adopt':
            set_comment(e, TAG)
        elif kind == 'add':
            set_comment(doc.Create.NewFamilyInstance(p, sym, view), TAG)
        elif kind == 'move':
            DB.ElementTransformUtils.MoveElement(doc, e.Id, p - e.Location.Point)
        elif kind == 'delete':
            doc.Delete(e.Id)


def counts(actions):
    out = {}
    for kind, _, _ in actions:
        out[kind] = out.get(kind, 0) + 1
    return out


def plan_all(doc, views=None):
    """[(view, actions)] for the views (all sections by default) that need changes,
    or None if the wall type or detail type is missing."""
    wt_id, sym = wall_type_id(doc), detail_symbol(doc)
    if wt_id is None or sym is None:
        return None, None
    out = []
    for v in (views if views is not None else section_views(doc)):
        if is_section(v):
            acts = plan(doc, v, sym, wt_id)
            if acts:
                out.append((v, acts))
    return sym, out


def sync(doc, views=None, name='Sync Sill X'):
    """Plan, then apply in one transaction only if something changed.  Returns
    {view name: counts} or None if the types are missing."""
    sym, work = plan_all(doc, views)
    if sym is None:
        return None
    if not work:
        return {}
    if not sym.IsActive:
        sym.Activate()
    t = DB.Transaction(doc, name)
    t.Start()
    try:
        for v, acts in work:
            apply(doc, v, sym, acts)
        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise
    return dict((v.Name, counts(acts)) for v, acts in work)
