"""2x8 sill plate on top of the FOUNDATION WALLS (NEW) wall type: a wall sweep
for the geometry, and Nominal Cut Lumber-Section detail components (the X for a
continuous member) wherever a section view cuts one of those walls.
"""
from pyrevit.api import DB
from System import Int64

WALL_TYPE = 'FOUNDATION WALLS (NEW)'
PROFILE_FAMILY, PROFILE_TYPE = 'Dimension Lumber-Profile', '2x8'
SILL_PROFILE = '2x8 SILL (FLAT)'
LUMBER_MAT = 18960                      # Softwood, Lumber
DETAIL_RFA = (r'C:\ProgramData\Autodesk\RVT 2026\Libraries\English-Imperial\US\Detail Items'
              r'\Wood and Plastic\Wood Framing\Nominal Cut Lumber-Section.rfa')
DETAIL_FAMILY, DETAIL_TYPE = 'Nominal Cut Lumber-Section', '2x8'
SILL_W, SILL_H = 7.25 / 12, 1.5 / 12   # flat 2x8


def a(x):
    if x is None:
        return None
    return ''.join(c if ord(c) < 128 else '?' for c in unicode(x))


def tname(e):
    p = e.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
    return p.AsString() if p else None


def eid(i):
    return DB.ElementId(Int64(i))


def symbol(doc, cat, family, type_name):
    for s in DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol).OfCategory(cat):
        if s.FamilyName == family and tname(s) == type_name:
            return s
    return None


def double_params(e):
    out = {}
    for p in e.Parameters:
        if p.StorageType == DB.StorageType.Double:
            out[a(p.Definition.Name)] = [round(p.AsDouble() * 12, 3), p.IsReadOnly]
    return out


def wall_type(doc):
    return [t for t in DB.FilteredElementCollector(doc).OfClass(DB.WallType) if tname(t) == WALL_TYPE][0]


def load_detail(doc):
    s = symbol(doc, DB.BuiltInCategory.OST_DetailComponents, DETAIL_FAMILY, DETAIL_TYPE)
    if s is not None:
        return s, False
    doc.LoadFamilySymbol(DETAIL_RFA, DETAIL_TYPE)       # only the 2x8 type from the catalog
    return symbol(doc, DB.BuiltInCategory.OST_DetailComponents, DETAIL_FAMILY, DETAIL_TYPE), True


def wall_frame(w):
    """Origin (start of location line), along, outward-normal unit vectors."""
    c = w.Location.Curve
    p0, p1 = c.GetEndPoint(0), c.GetEndPoint(1)
    along = (p1 - p0).Normalize()
    return p0, along, w.Orientation


def local_extents(w):
    """Wall solid extents (across: min, max relative to the location line; z: min, max)."""
    p0, along, out_n = wall_frame(w)
    across, zs = [], []
    opt = DB.Options()
    for g in w.get_Geometry(opt):
        if isinstance(g, DB.Solid) and g.Volume > 0:
            for e in g.Edges:
                for p in (e.AsCurve().GetEndPoint(0), e.AsCurve().GetEndPoint(1)):
                    across.append((p - p0).DotProduct(out_n))
                    zs.append(p.Z)
    return [round(min(across) * 12, 3), round(max(across) * 12, 3)], [round(min(zs), 4), round(max(zs), 4)]


FLAT_DETAIL = '2x8 FLAT'


def flat_profile(doc):
    """Profile type for a 2x8 laid flat (b = 7 1/4" across the wall, d = 1 1/2" up)."""
    s = symbol(doc, DB.BuiltInCategory.OST_ProfileFamilies, PROFILE_FAMILY, SILL_PROFILE)
    if s is None:
        base = symbol(doc, DB.BuiltInCategory.OST_ProfileFamilies, PROFILE_FAMILY, PROFILE_TYPE)
        s = base.Duplicate(SILL_PROFILE)
        s.LookupParameter('b').Set(SILL_W)
        s.LookupParameter('d').Set(SILL_H)
    return s


def flat_detail(doc):
    """Detail component type for a 2x8 seen flat in section (7 1/4" wide, 1 1/2" tall)."""
    s = symbol(doc, DB.BuiltInCategory.OST_DetailComponents, DETAIL_FAMILY, FLAT_DETAIL)
    if s is None:
        base, _ = load_detail(doc)
        s = base.Duplicate(FLAT_DETAIL)
        s.LookupParameter('Width').Set(SILL_W)
        s.LookupParameter('Depth').Set(SILL_H)
    if not s.IsActive:
        s.Activate()
    return s


def hosted_sweeps(doc, wall):
    return [s for s in DB.FilteredElementCollector(doc).OfClass(DB.WallSweep)
            if wall.Id in list(s.GetHostIds())]


def sweep_extents(doc, wall):
    """Extents of the sweeps on a wall: across (in, from the location line, + = exterior), z."""
    p0, along, out_n = wall_frame(wall)
    across, zs = [], []
    for s in hosted_sweeps(doc, wall):
        for g in s.get_Geometry(DB.Options()):
            solids = [g] if isinstance(g, DB.Solid) else (list(g.GetInstanceGeometry()) if isinstance(g, DB.GeometryInstance) else [])
            for so in solids:
                if isinstance(so, DB.Solid) and so.Volume > 0:
                    for e in so.Edges:
                        for p in (e.AsCurve().GetEndPoint(0), e.AsCurve().GetEndPoint(1)):
                            across.append((p - p0).DotProduct(out_n))
                            zs.append(p.Z)
    if not across:
        return None
    return [round(min(across) * 12, 3), round(max(across) * 12, 3)], [round(min(zs), 4), round(max(zs), 4)]


PROFILE_RFT = r'C:\ProgramData\Autodesk\RVT 2026\Family Templates\English-Imperial\Profile.rft'
SILL_FAMILY, SILL_FAMILY_TYPE = 'SILL PLATE - 2x8 FLAT', '2x8'
SWEEP_OFFSET = -4.0 / 12      # profile is centred on the exterior face: move it to the wall centre
SWEEP_DISTANCE = 0.0          # profile origin is its bottom edge: insert at the wall top, sill sits above


def sill_profile(doc, app):
    """Profile family with its origin at the bottom centre of a flat 7 1/4" x 1 1/2"
    rectangle, so a sweep inserted at the wall top sits on the concrete.  Built from
    the Profile template and loaded straight into the project (call with no open
    transaction in the project)."""
    s = symbol(doc, DB.BuiltInCategory.OST_ProfileFamilies, SILL_FAMILY, SILL_FAMILY_TYPE)
    if s is not None:
        return s, False
    fam_doc = app.NewFamilyDocument(PROFILE_RFT)
    try:
        view = [v for v in DB.FilteredElementCollector(fam_doc).OfClass(DB.ViewPlan) if not v.IsTemplate][0]
        t = DB.Transaction(fam_doc, 'sill profile')
        t.Start()
        hw = SILL_W / 2.0
        pts = [DB.XYZ(-hw, 0, 0), DB.XYZ(hw, 0, 0), DB.XYZ(hw, SILL_H, 0), DB.XYZ(-hw, SILL_H, 0)]
        for p, q in zip(pts, pts[1:] + pts[:1]):
            fam_doc.FamilyCreate.NewDetailCurve(view, DB.Line.CreateBound(p, q))
        t.Commit()
        fam = fam_doc.LoadFamily(doc)
    finally:
        fam_doc.Close(False)
    t = DB.Transaction(doc, 'name sill profile')
    t.Start()
    fam.Name = SILL_FAMILY
    s = doc.GetElement(list(fam.GetFamilySymbolIds())[0])
    s.Name = SILL_FAMILY_TYPE
    t.Commit()
    return s, True
SQUARE_TOL = 0.98             # |cos| between wall direction and section direction to treat the cut as square


def wall_top_at(wall, p):
    """Top of the wall's concrete on a vertical line through plan point p."""
    line = DB.Line.CreateBound(DB.XYZ(p.X, p.Y, p.Z - 50.0), DB.XYZ(p.X, p.Y, p.Z + 50.0))
    best = None
    for g in wall.get_Geometry(DB.Options()):
        if isinstance(g, DB.Solid) and g.Volume > 0:
            res = g.IntersectWithCurve(line, DB.SolidCurveIntersectionOptions())
            for k in range(res.SegmentCount):
                z = res.GetCurveSegment(k).GetEndPoint(1).Z
                best = z if best is None else max(best, z)
    return best


def section_cuts(doc, view, wall_type_id):
    """(wall, point on its centreline at the cut plane, status) for every wall of
    the type visible in the section view whose location line the cut plane crosses."""
    out = []
    origin, normal = view.Origin, view.ViewDirection
    crop = view.CropBox
    inv = crop.Transform.Inverse
    for w in DB.FilteredElementCollector(doc, view.Id).OfClass(DB.Wall):
        if w.GetTypeId() != wall_type_id or not isinstance(w.Location, DB.LocationCurve):
            continue
        c = w.Location.Curve
        if not isinstance(c, DB.Line):
            out.append((w, None, 'curved wall skipped'))
            continue
        p0, p1 = c.GetEndPoint(0), c.GetEndPoint(1)
        d0, d1 = (p0 - origin).DotProduct(normal), (p1 - origin).DotProduct(normal)
        if d0 * d1 > 0 or abs(d0 - d1) < 1e-9:
            continue                                   # plane does not cross this wall
        p = p0 + (p1 - p0) * (d0 / (d0 - d1))
        cos = abs((p1 - p0).Normalize().DotProduct(normal))
        local = inv.OfPoint(p)
        if view.CropBoxActive and not (crop.Min.X - 1e-3 <= local.X <= crop.Max.X + 1e-3):
            out.append((w, p, 'outside crop'))
            continue
        out.append((w, p, 'ok' if cos >= SQUARE_TOL else 'oblique cut skipped (cos %.2f)' % cos))
    return out


def place_section_details(doc, sym):
    """Flat 2x8 detail component over the sill wherever a section cuts the wall type."""
    wt = wall_type(doc)
    placed, skipped = [], []
    for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewSection):
        if v.IsTemplate or v.ViewType != DB.ViewType.Section:
            continue
        existing = [e for e in DB.FilteredElementCollector(doc, v.Id).OfClass(DB.FamilyInstance)
                    if e.Symbol.Id == sym.Id]
        for w, p, status in section_cuts(doc, v, wt.Id):
            if status != 'ok':
                skipped.append([a(v.Name), w.Id.Value, status])
                continue
            top = wall_top_at(w, p)
            if top is None:
                skipped.append([a(v.Name), w.Id.Value, 'no wall top found'])
                continue
            # detail origin is its bottom-left corner in the view: half a sill left of the centreline
            o = DB.XYZ(p.X, p.Y, top) - v.RightDirection * (SILL_W / 2.0)
            if any(e.Location.Point.DistanceTo(o) < 0.05 for e in existing):
                skipped.append([a(v.Name), w.Id.Value, 'already has a sill X'])
                continue
            inst = doc.Create.NewFamilyInstance(o, sym, v)
            placed.append([a(v.Name), w.Id.Value, inst.Id.Value, round(top, 3)])
    return placed, skipped


def run(doc, prof):
    wt = add_sweep(doc, prof.Id, SWEEP_OFFSET, SWEEP_DISTANCE)
    doc.Regenerate()
    sym = flat_detail(doc)
    doc.Regenerate()
    placed, skipped = place_section_details(doc, sym)
    doc.Regenerate()
    sample = doc.GetElement(eid(1410986))
    return {'profile': [prof.Id.Value, SILL_FAMILY + ' : ' + SILL_FAMILY_TYPE], 'detail_type': [sym.Id.Value, FLAT_DETAIL],
            'wall_type': [wt.Id.Value, WALL_TYPE],
            'sample_wall_1410986 (across in, z)': {'wall': local_extents(sample), 'sill': sweep_extents(doc, sample)},
            'wall_sweeps_created': len([s for s in DB.FilteredElementCollector(doc).OfClass(DB.WallSweep)
                                        if doc.GetElement(list(s.GetHostIds())[0]).GetTypeId() == wt.Id]),
            'section_X_placed [view, wall, detail id, sill bottom z]': placed,
            'skipped [view, wall, reason]': skipped}


def add_sweep(doc, profile_id, offset=0.0, distance=0.0, side=DB.WallSide.Exterior):
    t = wall_type(doc)
    cs = t.GetCompoundStructure()
    info = DB.WallSweepInfo(True, DB.WallSweepType.Sweep)     # fixed sweep in the wall type
    info.WallSweepOrientation = DB.WallSweepOrientation.Horizontal
    used = [s.Id for k in (DB.WallSweepType.Sweep, DB.WallSweepType.Reveal) for s in cs.GetWallSweepsInfo(k)]
    info.Id = max(used + [0]) + 1
    info.ProfileId = profile_id
    info.MaterialId = eid(LUMBER_MAT)
    info.DistanceMeasuredFrom = DB.DistanceMeasuredFrom.Top
    info.Distance = distance
    info.WallSide = side
    info.WallOffset = offset
    info.CutsWall = False
    info.IsCutByInserts = False
    cs.AddWallSweep(info)
    t.SetCompoundStructure(cs)
    return t
