"""Rebuild the PROPOSED sunroom roof framing to match roof_framing_model.py:
rafters at 24" o.c. with the king common, 1 3/4" x 11 7/8" LVL ceiling joists at
16" o.c. plus a joist under each post, and the ridge post on the E-W bearing
wall at 19'-7 1/2".  Ridge and hips are kept (their geometry is unchanged).

Script coords: X = east, Y = up, Z = south, origin = NW plate corner.
Model: x = X0 - X, y = Y0 + Z, z = plate + Y.
"""
import math
from pyrevit.api import DB
from System import Int64

X0, Y0 = -58.0832, -19.8133
WIDTH, LENGTH = 22.625, 25.313
PITCH = 10.0 / 12.0
RUN = WIDTH / 2.0
H_RIDGE = RUN * PITCH
RAFTER_SPACING = 24.0 / 12.0
JOIST_SPACING = 16.0 / 12.0
BEARING_WALL_Z = 19.0 + 7.5 / 12.0
OPTION = 'PROPOSED'
PHASE = 'Adair Addition'
RAFTER_TYPE = ('Dimension Lumber', '2x8')
JOIST_TYPE = ('LVL-Laminated Veneer Lumber', '(1) 1 3/4x11 7/8')
JOIST_D = 11.875 / 12
REPLACE = ('JACK_', 'KING_', 'COMMON_', 'CJ_')
RIDGE_POST = 'POST - RIDGE @ BEARING WALL'
OLD_RIDGE_POST = 'POST - RIDGE @ BATH WALL'


def a(x):
    return None if x is None else ''.join(c if ord(c) < 128 else '?' for c in unicode(x))


def eid(i):
    return DB.ElementId(Int64(i))


def tname(e):
    p = e.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
    return p.AsString() if p else None


def comment(e):
    return e.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).AsString() or ''


def in_option(e):
    return e.DesignOption is not None and e.DesignOption.Name.startswith(OPTION)


def layout(length, s):
    pts, k = [], 1
    while k * s < length - 1e-6:
        pts.append(k * s)
        k += 1
    return pts


def to_model(X, Y, Z, plate):
    return DB.XYZ(X0 - X, Y0 + Z, plate + Y)


def rafters():
    """(name, start, end) in script coords, as in roof_framing_model.build()."""
    out = []
    jack_off = layout(RUN, RAFTER_SPACING)
    north_x = jack_off + [RUN] + [WIDTH - o for o in jack_off]
    for x in north_x:
        off = min(x, WIDTH - x)
        tag = 'KING_N' if abs(x - RUN) < 1e-6 else 'JACK_N_%.2f' % x
        out.append((tag, (x, 0.0, 0.0), (x, off * PITCH, off)))
    n_sp = int(math.ceil((LENGTH - RUN) / RAFTER_SPACING - 1e-9))
    side_z = jack_off + [RUN + i * (LENGTH - RUN) / n_sp for i in range(n_sp + 1)]
    for side, x0, sgn in (('W', 0.0, 1), ('E', WIDTH, -1)):
        for z in side_z:
            if z < RUN - 1e-6:
                top, tag = (x0 + sgn * z, z * PITCH, z), 'JACK_%s_%.2f' % (side, z)
            else:
                top, tag = (RUN, H_RIDGE, z), 'COMMON_%s_%.2f' % (side, z)
            out.append((tag, (x0, 0.0, z), top))
    return out


POST_X = [RUN, RUN / 2.0, WIDTH - RUN / 2.0]


def joists():
    xs = layout(WIDTH, JOIST_SPACING)
    for px in POST_X:
        near = [jx for jx in xs if abs(jx - px) < 0.15]
        if near:
            xs[xs.index(near[0])] = px
        else:
            xs.append(px)
    return [('CJ_%.2f' % x, (x, 0.0, 0.0), (x, 0.0, LENGTH)) for x in sorted(xs)]


def symbol(doc, fam, typ):
    for s in DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol).OfCategory(DB.BuiltInCategory.OST_StructuralFraming):
        if s.FamilyName == fam and tname(s) == typ:
            return s
    raise Exception('type not found: %s : %s' % (fam, typ))


def settings_of(e):
    """Placement settings to copy from an existing member (new beams otherwise
    inherit Revit's last-used values, e.g. a stray Z offset)."""
    return dict(z=e.get_Parameter(DB.BuiltInParameter.Z_JUSTIFICATION).AsInteger(),
                y=e.get_Parameter(DB.BuiltInParameter.Y_JUSTIFICATION).AsInteger(),
                z_off=e.get_Parameter(DB.BuiltInParameter.Z_OFFSET_VALUE).AsDouble(),
                y_off=e.get_Parameter(DB.BuiltInParameter.Y_OFFSET_VALUE).AsDouble())


def run(doc):
    level = [l for l in DB.FilteredElementCollector(doc).OfClass(DB.Level) if l.Name == 'TOP OF WALLS'][0]
    plate = level.ProjectElevation
    phase = [p for p in doc.Phases if p.Name == PHASE][0]
    framing = [e for e in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_StructuralFraming)
               .WhereElementIsNotElementType() if in_option(e)]
    rafter_set = settings_of([e for e in framing if comment(e).startswith('JACK_')][0])
    joist_set = settings_of([e for e in framing if comment(e).startswith('CJ_')][0])
    out = {'kept': [[e.Id.Value, comment(e), a(e.Name)] for e in framing if comment(e).startswith(('RIDGE', 'HIP_'))],
           'justification': {'rafters': rafter_set, 'joists': joist_set}}

    old = [e for e in framing if comment(e).startswith(REPLACE)]
    out['deleted'] = {}
    for e in old:
        g = comment(e).split('_')[0]
        out['deleted'][g] = out['deleted'].get(g, 0) + 1
        doc.Delete(e.Id)

    rsym, jsym = symbol(doc, *RAFTER_TYPE), symbol(doc, *JOIST_TYPE)
    for s in (rsym, jsym):
        if not s.IsActive:
            s.Activate()
    doc.Regenerate()
    created = {}
    for members, sym, sets in ((rafters(), rsym, rafter_set), (joists(), jsym, joist_set)):
        for name, p, q in members:
            line = DB.Line.CreateBound(to_model(p[0], p[1], p[2], plate), to_model(q[0], q[1], q[2], plate))
            fi = doc.Create.NewFamilyInstance(line, sym, level, DB.Structure.StructuralType.Beam)
            DB.Structure.StructuralFramingUtils.DisallowJoinAtEnd(fi, 0)
            DB.Structure.StructuralFramingUtils.DisallowJoinAtEnd(fi, 1)
            fi.get_Parameter(DB.BuiltInParameter.Z_JUSTIFICATION).Set(sets['z'])
            fi.get_Parameter(DB.BuiltInParameter.Y_JUSTIFICATION).Set(sets['y'])
            fi.get_Parameter(DB.BuiltInParameter.Z_OFFSET_VALUE).Set(sets['z_off'])
            fi.get_Parameter(DB.BuiltInParameter.Y_OFFSET_VALUE).Set(sets['y_off'])
            fi.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).Set(name)
            fi.get_Parameter(DB.BuiltInParameter.PHASE_CREATED).Set(phase.Id)
            g = name.split('_')[0]
            created[g] = created.get(g, 0) + 1
    out['created'] = created
    out['joist_x'] = [round(float(n[3:]), 3) for n, _, _ in joists()]
    doc.Regenerate()

    # Posts: ridge post to the bearing wall; all posts on top of the LVL joists
    base_off = JOIST_D if joist_set['z'] == 3 else JOIST_D / 2.0     # bottom- or centre-justified joists
    out['posts'] = []
    for e in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_StructuralColumns).WhereElementIsNotElementType():
        c = comment(e)
        if not c.startswith('POST'):
            continue
        before = e.Location.Point
        if c in (OLD_RIDGE_POST, RIDGE_POST):
            target_y = Y0 + BEARING_WALL_Z
            DB.ElementTransformUtils.MoveElement(doc, e.Id, DB.XYZ(0.0, target_y - before.Y, 0.0))
            e.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).Set(RIDGE_POST)
            c = RIDGE_POST
        e.get_Parameter(DB.BuiltInParameter.FAMILY_BASE_LEVEL_OFFSET_PARAM).Set(base_off)
        out['posts'].append({'id': e.Id.Value, 'label': c, 'moved_y_in': round((e.Location.Point.Y - before.Y) * 12, 3)})
    doc.Regenerate()

    # Each post should sit on a joist: same x, within the joist's length, base at the joist top
    new_joists = [e for e in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_StructuralFraming)
                  .WhereElementIsNotElementType() if in_option(e) and comment(e).startswith('CJ_')]
    for p in out['posts']:
        col = doc.GetElement(eid(p['id']))
        pt = col.Location.Point
        hit = None
        for j in new_joists:
            c = j.Location.Curve
            s, t = c.GetEndPoint(0), c.GetEndPoint(1)
            if abs(s.X - pt.X) < 0.01 and min(s.Y, t.Y) - 0.01 <= pt.Y <= max(s.Y, t.Y) + 0.01:
                zs = []
                for g in j.get_Geometry(DB.Options()):
                    sol = [g] if isinstance(g, DB.Solid) else (
                        list(g.GetInstanceGeometry()) if isinstance(g, DB.GeometryInstance) else [])
                    for so in sol:
                        if isinstance(so, DB.Solid) and so.Volume > 0:
                            for ed in so.Edges:
                                zs += [ed.AsCurve().GetEndPoint(0).Z, ed.AsCurve().GetEndPoint(1).Z]
                hit = [comment(j), round(max(zs), 3) if zs else None]
        cb = col.get_BoundingBox(None)
        p['on_joist [name, joist top z]'] = hit
        p['post_bottom_z'] = round(cb.Min.Z, 3)
        p['post_top_z'] = round(cb.Max.Z, 3)
    return out
