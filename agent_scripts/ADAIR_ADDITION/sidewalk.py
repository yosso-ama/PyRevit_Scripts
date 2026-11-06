"""South walkway for the lower addition (PROPOSED LAYOUT), from the marked-up
foundation plan: a pad at the shop, a 3'-0" walk along the south walls rising
from the shop floor to the safe-room floor, and a landing south of the safe
room.  4" concrete over 4" base rock.  Plan coordinates are internal feet.
"""
from pyrevit.api import DB
from System import Int64
from System.Collections.Generic import List

TYPE_NAME = 'SIDEWALK - 4" CONC / 4" BASE ROCK'
CONCRETE_MAT = 18939      # Concrete, Cast-in-Place gray
ROCK_MAT = 1182145        # Gravel
TOPO_ID = 1456799         # PROPOSED LAYOUT toposolid
PHASE_NAME = 'Adair Addition'

SHOP_FFE = 978.893        # FFE SHOP
SHELTER_FFE = 980.06      # FFE SHELTER (safe room)
STAIR_SLAB_TOP = 980.018  # existing 6" foundation slab 1465167 south of the safe room (FFE SHELTER - 1/2")
WALK_W = 3.0              # walkway width off the wall face

# Wall faces (south / outside)
SHOP_FACE, MIDDLE_FACE, SHELTER_FACE = -19.479, -18.5, -20.0
SHOP_MID_X, MID_SHELTER_X = -57.792, -28.0

PAD = [(-72.66, -24.0), (-65.66, -24.0), (-65.66, SHOP_FACE), (-72.66, SHOP_FACE)]
WALK_W_X, WALK_STEP_X, WALK_E_X = -65.66, -55.56, -35.50   # east end = west edge of the stair slab
WALK = [(WALK_W_X, SHOP_FACE - WALK_W), (WALK_STEP_X, SHOP_FACE - WALK_W),
        (WALK_STEP_X, MIDDLE_FACE - WALK_W), (WALK_E_X, MIDDLE_FACE - WALK_W),
        (WALK_E_X, MIDDLE_FACE), (SHOP_MID_X, MIDDLE_FACE), (SHOP_MID_X, SHOP_FACE),
        (WALK_W_X, SHOP_FACE)]
LANDING_E_X, LANDING_S_Y = -17.32, -25.58
LANDING = [(WALK_E_X, LANDING_S_Y), (LANDING_E_X, LANDING_S_Y), (LANDING_E_X, SHELTER_FACE),
           (MID_SHELTER_X, SHELTER_FACE), (MID_SHELTER_X, MIDDLE_FACE), (WALK_E_X, MIDDLE_FACE)]
SLOPE = (STAIR_SLAB_TOP - SHOP_FFE) / (WALK_E_X - WALK_W_X)
USE_LANDING = False       # the existing stair slab already covers the landing


def eid(i):
    return DB.ElementId(Int64(i))


def level(doc, name):
    return [l for l in DB.FilteredElementCollector(doc).OfClass(DB.Level) if l.Name == name][0]


def loop(pts, z):
    cl = DB.CurveLoop()
    for a, b in zip(pts, pts[1:] + pts[:1]):
        cl.Append(DB.Line.CreateBound(DB.XYZ(a[0], a[1], z), DB.XYZ(b[0], b[1], z)))
    return List[DB.CurveLoop]([cl])


def sidewalk_type(doc):
    existing = [t for t in DB.FilteredElementCollector(doc).OfClass(DB.FloorType)
                if DB.Element.Name.GetValue(t) == TYPE_NAME]
    if existing:
        return existing[0], False
    base = [t for t in DB.FilteredElementCollector(doc).OfClass(DB.FloorType)
            if DB.Element.Name.GetValue(t) == 'Concrete 4"'][0]
    t = base.Duplicate(TYPE_NAME)
    layers = List[DB.CompoundStructureLayer]()
    layers.Add(DB.CompoundStructureLayer(4.0 / 12, DB.MaterialFunctionAssignment.Structure, eid(CONCRETE_MAT)))
    layers.Add(DB.CompoundStructureLayer(4.0 / 12, DB.MaterialFunctionAssignment.Substrate, eid(ROCK_MAT)))
    cs = t.GetCompoundStructure()          # keeps the floor's own end-cap settings
    cs.SetLayers(layers)
    cs.StructuralMaterialIndex = 0
    t.SetCompoundStructure(cs)
    return t, True


def top_z(elem, x, y):
    line = DB.Line.CreateBound(DB.XYZ(x, y, 950.0), DB.XYZ(x, y, 1020.0))
    best = None
    for g in elem.get_Geometry(DB.Options()):
        if isinstance(g, DB.Solid) and g.Volume > 0:
            res = g.IntersectWithCurve(line, DB.SolidCurveIntersectionOptions())
            for k in range(res.SegmentCount):
                z = res.GetCurveSegment(k).GetEndPoint(1).Z
                best = z if best is None else max(best, z)
    return best


def solids(e):
    out = []
    for g in e.get_Geometry(DB.Options()):
        if isinstance(g, DB.Solid) and g.Volume > 0:
            out.append(g)
        elif isinstance(g, DB.GeometryInstance):
            out += [s for s in g.GetInstanceGeometry() if isinstance(s, DB.Solid) and s.Volume > 0]
    return out


def overlap(a, b):
    v = 0.0
    for s1 in solids(a):
        for s2 in solids(b):
            try:
                v += DB.BooleanOperationsUtils.ExecuteBooleanOperation(
                    s1, s2, DB.BooleanOperationsType.Intersect).Volume
            except Exception:
                pass
    return v


WALK_MODE = 'shape'       # 'arrow' = slope arrow, 'shape' = flat floor with shape-edited vertices, 'flat'
WALL_GAP = 0.0            # ft kept between the walk and the wall faces


END_GAP = 0.0             # ft kept between the walk's east end and the stair slab


def walk_outline():
    faces = (SHOP_FACE, MIDDLE_FACE)
    pts = []
    for x, y in WALK:
        if WALL_GAP and any(abs(y - f) < 1e-6 for f in faces):
            y -= WALL_GAP
        if END_GAP and abs(x - WALK_E_X) < 1e-6:
            x -= END_GAP
        if WALL_GAP and abs(x - SHOP_MID_X) < 1e-6:
            x -= WALL_GAP                      # keep off the end face of the middle wall too
        pts.append((x, y))
    return pts


def walk_z(x):
    """Walk top elevation at plan x: shop floor at the west end, stair slab at the east."""
    x = min(max(x, WALK_W_X), WALK_E_X)
    return SHOP_FFE + SLOPE * (x - WALK_W_X)


def make_walk(doc, ftype, shop):
    outline = walk_outline()
    if WALK_MODE == 'arrow':
        arrow = DB.Line.CreateBound(DB.XYZ(WALK_W_X, -20.5, SHOP_FFE), DB.XYZ(WALK_E_X, -20.5, SHOP_FFE))
        return DB.Floor.Create(doc, loop(outline, SHOP_FFE), ftype.Id, shop.Id, False, arrow, SLOPE)
    walk = DB.Floor.Create(doc, loop(outline, SHOP_FFE), ftype.Id, shop.Id)
    if WALK_MODE == 'shape':
        doc.Regenerate()
        ed = walk.GetSlabShapeEditor()
        ed.Enable()
        doc.Regenerate()                       # vertices exist only after regeneration
        ed = walk.GetSlabShapeEditor()
        for v in list(ed.SlabShapeVertices):
            ed.ModifySubElement(v, walk_z(v.Position.X) - SHOP_FFE)
        doc.Regenerate()
    return walk


def build(doc, excavate=True, excavate_only=None):
    ftype, new_type = sidewalk_type(doc)
    shop, shelter = level(doc, 'FFE SHOP'), level(doc, 'FFE SHELTER')
    phase = [p for p in doc.Phases if p.Name == PHASE_NAME][0]
    pad = DB.Floor.Create(doc, loop(PAD, SHOP_FFE), ftype.Id, shop.Id)
    walk = make_walk(doc, ftype, shop)
    floors = [('pad', pad), ('walk', walk)]
    if USE_LANDING:
        floors.append(('landing', DB.Floor.Create(doc, loop(LANDING, SHELTER_FFE), ftype.Id, shelter.Id)))
    for name, f in floors:
        f.get_Parameter(DB.BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM).Set(0.0)
        f.get_Parameter(DB.BuiltInParameter.PHASE_CREATED).Set(phase.Id)
        f.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).Set('SOUTH WALKWAY - ' + name.upper())
    doc.Regenerate()

    topo = doc.GetElement(eid(TOPO_ID))
    excavated, refused = [], []
    for name, f in floors:
        if not excavate or (excavate_only is not None and name not in excavate_only):
            continue
        try:
            if topo.CanBeExcavatedBy(f.Id):
                topo.ExcavateBy(f.Id)
                excavated.append(name)
            else:
                refused.append(name)
        except Exception as ex:
            refused.append('%s: %s' % (name, str(ex)[:80]))
    doc.Regenerate()
    return ftype, new_type, floors, excavated, refused


THICK = 8.0 / 12           # 4" concrete + 4" base rock
UNDER_CLEAR = 0.125 / 12   # soil kept 1/8" below the base rock
BLEND = 4.0                # ft beyond the walk edge where grade returns to existing
FOOTPRINT = [(-72.66, SHOP_FACE), (SHOP_MID_X, SHOP_FACE), (SHOP_MID_X, MIDDLE_FACE),
             (WALK_E_X, MIDDLE_FACE), (WALK_E_X, MIDDLE_FACE - WALK_W),
             (WALK_STEP_X, MIDDLE_FACE - WALK_W), (WALK_STEP_X, SHOP_FACE - WALK_W),
             (WALK_W_X, SHOP_FACE - WALK_W), (WALK_W_X, -24.0), (-72.66, -24.0)]
# Outside edges (not against a wall or the stair slab), each with its outward normal
OPEN_EDGES = [((WALK_E_X, MIDDLE_FACE - WALK_W), (WALK_STEP_X, MIDDLE_FACE - WALK_W), (0.0, -1.0)),
              ((WALK_STEP_X, MIDDLE_FACE - WALK_W), (WALK_STEP_X, SHOP_FACE - WALK_W), (-1.0, 0.0)),
              ((WALK_STEP_X, SHOP_FACE - WALK_W), (WALK_W_X, SHOP_FACE - WALK_W), (0.0, -1.0)),
              ((WALK_W_X, SHOP_FACE - WALK_W), (WALK_W_X, -24.0), (1.0, 0.0)),
              ((WALK_W_X, -24.0), (-72.66, -24.0), (0.0, -1.0)),
              ((-72.66, -24.0), (-72.66, SHOP_FACE), (-1.0, 0.0))]


def top_at(x):
    """Finished top of the pad / walk at plan x."""
    return SHOP_FFE if x <= WALK_W_X else walk_z(x)


def inside(poly, x, y):
    c = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def seg_points(a, b, step):
    n = max(1, int(round(((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5 / step)))
    return [(a[0] + (b[0] - a[0]) * k / float(n), a[1] + (b[1] - a[1]) * k / float(n)) for k in range(n + 1)]


def grade_points(topo):
    """Shape points: soil under the walk, flush grade at its open edges, and a
    blend back to existing grade BLEND ft out."""
    pts = []
    xs = [p[0] for p in FOOTPRINT]
    ys = [p[1] for p in FOOTPRINT]
    x = min(xs) + 0.25
    while x < max(xs):
        y = min(ys) + 0.25
        while y < max(ys):
            if inside(FOOTPRINT, x, y) and all(abs(y - f) > 0.2 for f in (SHOP_FACE, MIDDLE_FACE)):
                pts.append((x, y, top_at(x) - THICK - UNDER_CLEAR))
            y += 1.5
        x += 1.5
    # along the walls, just off the faces: soil stays under the rock right to the wall
    for a, b in (((-72.66, SHOP_FACE), (SHOP_MID_X, SHOP_FACE)), ((SHOP_MID_X, MIDDLE_FACE), (WALK_E_X, MIDDLE_FACE))):
        for px, py in seg_points(a, b, 1.0):
            pts.append((px, py - 0.05, top_at(px) - THICK - UNDER_CLEAR))
    # east end against the stair slab
    for px, py in seg_points((WALK_E_X, MIDDLE_FACE - 0.05), (WALK_E_X, MIDDLE_FACE - WALK_W), 0.5):
        pts.append((px - 0.05, py, top_at(px) - THICK - UNDER_CLEAR))
    for a, b, (nx, ny) in OPEN_EDGES:
        for px, py in seg_points(a, b, 1.0):
            # soil drops to under the rock 1/8" outside the edge (never touching the slab edge),
            # and is flush with the walk top a little further out
            pts.append((px + nx * 0.0104, py + ny * 0.0104, top_at(px) - THICK - UNDER_CLEAR))
            pts.append((px + nx * 0.05, py + ny * 0.05, top_at(px)))
            for d in (1.0, 2.0, 3.0):
                gx, gy = px + nx * d, py + ny * d
                if inside(FOOTPRINT, gx, gy):
                    continue
                e = top_z(topo, px + nx * BLEND, py + ny * BLEND)
                if e is not None:
                    pts.append((gx, gy, top_at(px) + (e - top_at(px)) * d / BLEND))
    return pts


def capture_topo_spots(doc):
    """Spot elevations hosted on the toposolid: reshaping re-triangulates the
    faces they reference, so they are recorded, deleted and placed again."""
    spots = []
    for sd in DB.FilteredElementCollector(doc).OfClass(DB.SpotDimension):
        if not any(r.ElementId.Value == TOPO_ID for r in sd.References):
            continue
        g = lambda name: getattr(sd, name, None)
        spots.append({'old_id': sd.Id.Value, 'view': sd.OwnerViewId, 'type': sd.GetTypeId(),
                      'origin': sd.Origin, 'end': g('LeaderEndPosition'),
                      'shoulder': g('LeaderShoulderPosition') if g('LeaderHasShoulder') else None,
                      'has_leader': bool(g('HasLeader')), 'text': g('TextPosition')})
    for s in spots:
        doc.Delete(eid(s['old_id']))
    return spots


def topo_face_ref(topo, x, y):
    """(reference, point) of the toposolid's top face at plan (x, y)."""
    opt = DB.Options()
    opt.ComputeReferences = True
    z = top_z(topo, x, y)
    if z is None:
        return None, None
    p = DB.XYZ(x, y, z)
    for g in topo.get_Geometry(opt):
        if not isinstance(g, DB.Solid):
            continue
        for f in g.Faces:
            r = f.Project(p)
            if r is not None and r.Distance < 1e-3 and f.ComputeNormal(r.UVPoint).Z > 0.1:
                return f.Reference, p
    return None, None


def replace_topo_spots(doc, spots):
    topo = doc.GetElement(eid(TOPO_ID))
    out = []
    for s in spots:
        ref, p = topo_face_ref(topo, s['origin'].X, s['origin'].Y)
        if ref is None:
            out.append([s['old_id'], None, 'no face found'])
            continue
        view = doc.GetElement(s['view'])
        end = s['end'] or p
        bend = s['shoulder'] or end
        try:
            sd = doc.Create.NewSpotElevation(view, ref, p, bend, end, p, s['has_leader'])
            sd.ChangeTypeId(s['type'])
            if s['text'] is not None:
                try:
                    sd.TextPosition = s['text']
                except Exception:
                    pass
            out.append([s['old_id'], sd.Id.Value, round(p.Z, 3)])
        except Exception as ex:
            out.append([s['old_id'], None, str(ex)[:80]])
    return out


def regrade_under(doc):
    topo = doc.GetElement(eid(TOPO_ID))
    spots = capture_topo_spots(doc)
    editor = topo.GetSlabShapeEditor()
    zone = lambda x, y: (min(p[0] for p in FOOTPRINT) - BLEND <= x <= max(p[0] for p in FOOTPRINT) + 0.5 and
                         -24.0 - BLEND <= y <= MIDDLE_FACE)
    pts = grade_points(topo)
    # Existing points are kept: spot elevations in the views reference them
    kept = [[round(v.Position.X, 2), round(v.Position.Y, 2), round(v.Position.Z, 3)]
            for v in editor.SlabShapeVertices if zone(v.Position.X, v.Position.Y)]
    removed = 0
    taken = set((round(v.Position.X, 2), round(v.Position.Y, 2)) for v in editor.SlabShapeVertices)
    near = [(v.Position.X, v.Position.Y) for v in editor.SlabShapeVertices]
    pts = [p for p in pts if all((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 > 0.25 ** 2 for q in near)]
    add = []
    for x, y, z in pts:
        k = (round(x, 2), round(y, 2))
        if k not in taken:
            taken.add(k)
            add.append(DB.XYZ(x, y, z))
    editor.AddPoints(List[DB.XYZ](add))
    doc.Regenerate()
    replaced = replace_topo_spots(doc, spots)
    doc.Regenerate()
    return {'topo_points_removed': removed, 'topo_points_added': len(add), 'existing_points_in_zone': kept,
            'spot_elevations_replaced [old, new, z]': replaced}


def report(doc, ftype, new_type, floors, excavated, refused):
    topo = doc.GetElement(eid(TOPO_ID))
    r2 = lambda v: None if v is None else round(v, 3)
    walk_tops = []
    for x in (-69.0, -65.0, -60.0, -56.0, -50.0, -45.0, -40.0, -36.5):
        y = -20.7 if x > WALK_E_X else (-20.5 if x > WALK_STEP_X else -21.0)
        z = max(filter(None, [top_z(f, x, y) for _, f in floors]) or [None])
        # grade just past the outside edge of the walk / pad / landing
        if x < WALK_W_X:
            ey = -24.0 - 0.5
        elif x < WALK_STEP_X:
            ey = SHOP_FACE - WALK_W - 0.5
        elif x < WALK_E_X:
            ey = MIDDLE_FACE - WALK_W - 0.5
        else:
            ey = LANDING_S_Y - 0.5
        walk_tops.append({'x': x, 'walk_top': r2(z), 'grade_0.5ft_outside': r2(top_z(topo, x, ey)),
                          'grade_3ft_outside': r2(top_z(topo, x, ey - 2.5)),
                          'soil_under_walk': r2(top_z(topo, x, ey + 1.5))})
    # clashes with PROPOSED footings and walls
    opt = topo.DesignOption.Id
    clashes = []
    for cat in (DB.BuiltInCategory.OST_StructuralFoundation, DB.BuiltInCategory.OST_Walls):
        for e in DB.FilteredElementCollector(doc).OfCategory(cat).WhereElementIsNotElementType():
            if e.DesignOption is not None and e.DesignOption.Id != opt:
                continue
            for name, f in floors:
                v = overlap(f, e)
                if v > 1e-4:
                    clashes.append([name, e.Id.Value, e.Name, round(v, 3)])
    return {'type': [ftype.Id.Value, DB.Element.Name.GetValue(ftype), 'new' if new_type else 'existing',
                     round(ftype.GetCompoundStructure().GetWidth() * 12, 2)],
            'floors': [[n, f.Id.Value, f.DesignOption.Name if f.DesignOption else 'Main Model',
                        round(f.get_Parameter(DB.BuiltInParameter.HOST_AREA_COMPUTED).AsDouble(), 1)]
                       for n, f in floors],
            'walk_slope_pct': round(SLOPE * 100, 2),
            'excavated_by': excavated, 'not_excavated': refused,
            'soil_overlap_ft3': dict((n, round(overlap(topo, f), 4)) for n, f in floors),
            'profile': walk_tops, 'clashes_ft3': clashes}
