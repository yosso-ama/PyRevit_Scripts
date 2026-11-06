"""Rebuild the whole PROPOSED sunroom roof framing on the as-built footprint
(22'-11" x 24'-11 3/4") to match roof_framing_model.py: (2)2x12 ridge and hips,
2x8 rafters at 24" o.c. with the king common, 1 3/4" x 9 1/4" LVL ceiling joists
at 24" o.c. with (2) LVL joists under the posts, and the four 4x6 posts moved
onto them (ridge post on the bearing wall at 19'-7 1/2").

Script coords: X = east, Y = up, Z = south, origin = NW plate corner (outside
faces).  Model: x = X0 - X, y = Y0 + Z, z = plate + Y.
"""
import math
from pyrevit.api import DB
from System import Int64

X0, Y0 = -57.787, -19.479            # east and end-wall outside faces (PROPOSED walls 1395816, 1393629)
WIDTH, LENGTH = 22.921, 24.979
PITCH = 10.0 / 12.0
RUN = WIDTH / 2.0
H_RIDGE = RUN * PITCH
RAFTER_SPACING = JOIST_SPACING = 24.0 / 12.0
BEARING_WALL_Z = 19.0 + 7.5 / 12.0
OPTION, PHASE = 'PROPOSED', 'Adair Addition'
LVL_FAMILY = 'LVL-Laminated Veneer Lumber'
JOIST_TYPE, POST_JOIST_TYPE = '(1) 1 3/4x9 1/4', '(2) 1 3/4x9 1/4'
JOIST_D = 9.25 / 12
REBUILD = ('RIDGE', 'HIP_', 'JACK_', 'KING_', 'COMMON_', 'CJ_')
POST_X = [RUN, RUN / 2.0, WIDTH - RUN / 2.0]
POSTS = {   # label -> script (X, Z) of the post, the beam it carries
    'POST - APEX': (RUN, RUN, 'RIDGE'),
    'POST - RIDGE @ BEARING WALL': (RUN, BEARING_WALL_Z, 'RIDGE'),
    'POST - HIP W MID': (RUN / 2.0, RUN / 2.0, 'HIP_W'),
    'POST - HIP E MID': (WIDTH - RUN / 2.0, RUN / 2.0, 'HIP_E'),
}
OLD_LABELS = {'POST - RIDGE @ BATH WALL': 'POST - RIDGE @ BEARING WALL'}


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


def to_model(p, plate):
    return DB.XYZ(X0 - p[0], Y0 + p[2], plate + p[1])


def members():
    """(name, group, start, end) in script coords, as in roof_framing_model.build()."""
    out = []
    apex = (RUN, H_RIDGE, RUN)
    out.append(('RIDGE', 'ridge', apex, (RUN, H_RIDGE, LENGTH)))
    out.append(('HIP_W', 'hip', (0.0, 0.0, 0.0), apex))
    out.append(('HIP_E', 'hip', (WIDTH, 0.0, 0.0), apex))
    jack_off = layout(RUN, RAFTER_SPACING)
    for x in jack_off + [RUN] + [WIDTH - o for o in jack_off]:
        off = min(x, WIDTH - x)
        tag = 'KING_N' if abs(x - RUN) < 1e-6 else 'JACK_N_%.2f' % x
        out.append((tag, 'rafter', (x, 0.0, 0.0), (x, off * PITCH, off)))
    n_sp = int(math.ceil((LENGTH - RUN) / RAFTER_SPACING - 1e-9))
    side_z = jack_off + [RUN + i * (LENGTH - RUN) / n_sp for i in range(n_sp + 1)]
    for side, x0, sgn in (('W', 0.0, 1), ('E', WIDTH, -1)):
        for z in side_z:
            if z < RUN - 1e-6:
                top, tag = (x0 + sgn * z, z * PITCH, z), 'JACK_%s_%.2f' % (side, z)
            else:
                top, tag = (RUN, H_RIDGE, z), 'COMMON_%s_%.2f' % (side, z)
            out.append((tag, 'rafter', (x0, 0.0, z), top))
    xs = layout(WIDTH, JOIST_SPACING)
    for px in POST_X:
        near = [jx for jx in xs if abs(jx - px) < 0.15]
        if near:
            xs[xs.index(near[0])] = px
        else:
            xs.append(px)
    for x in sorted(xs):
        grp = 'post_joist' if any(abs(x - px) < 1e-6 for px in POST_X) else 'joist'
        out.append(('CJ_%.2f' % x, grp, (x, 0.0, 0.0), (x, 0.0, LENGTH)))
    return out


def framing_symbol(doc, fam, typ):
    for s in DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol).OfCategory(DB.BuiltInCategory.OST_StructuralFraming):
        if s.FamilyName == fam and tname(s) == typ:
            return s
    return None


def lvl_type(doc, name, b, d):
    s = framing_symbol(doc, LVL_FAMILY, name)
    if s is None:
        base = framing_symbol(doc, LVL_FAMILY, '(1) 1 3/4x11 7/8')
        s = base.Duplicate(name)
        s.LookupParameter('b').Set(b)
        s.LookupParameter('d').Set(d)
    if not s.IsActive:
        s.Activate()
    return s


def settings_of(e):
    """Placement settings to copy (new beams otherwise inherit Revit's last-used values)."""
    return dict(z=e.get_Parameter(DB.BuiltInParameter.Z_JUSTIFICATION).AsInteger(),
                y=e.get_Parameter(DB.BuiltInParameter.Y_JUSTIFICATION).AsInteger(),
                z_off=e.get_Parameter(DB.BuiltInParameter.Z_OFFSET_VALUE).AsDouble(),
                y_off=e.get_Parameter(DB.BuiltInParameter.Y_OFFSET_VALUE).AsDouble(),
                level=e.get_Parameter(DB.BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM).AsElementId(),
                symbol=e.Symbol)


def solids(e):
    out = []
    for g in e.get_Geometry(DB.Options()):
        if isinstance(g, DB.Solid) and g.Volume > 0:
            out.append(g)
        elif isinstance(g, DB.GeometryInstance):
            out += [s for s in g.GetInstanceGeometry() if isinstance(s, DB.Solid) and s.Volume > 0]
    return out


def z_range_at(e, x, y):
    """(bottom, top) of element e on a vertical line through (x, y), or None."""
    line = DB.Line.CreateBound(DB.XYZ(x, y, 950.0), DB.XYZ(x, y, 1030.0))
    zs = []
    for s in solids(e):
        res = s.IntersectWithCurve(line, DB.SolidCurveIntersectionOptions())
        for k in range(res.SegmentCount):
            seg = res.GetCurveSegment(k)
            zs += [seg.GetEndPoint(0).Z, seg.GetEndPoint(1).Z]
    return (min(zs), max(zs)) if zs else None


def run(doc):
    level = [l for l in DB.FilteredElementCollector(doc).OfClass(DB.Level) if l.Name == 'TOP OF WALLS'][0]
    plate = level.ProjectElevation
    phase = [p for p in doc.Phases if p.Name == PHASE][0]
    framing = [e for e in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_StructuralFraming)
               .WhereElementIsNotElementType() if in_option(e)]
    pick = lambda prefix: [e for e in framing if comment(e).startswith(prefix)][0]
    sets = {'ridge': settings_of(pick('RIDGE')), 'hip': settings_of(pick('HIP_')),
            'rafter': settings_of(pick('JACK_')), 'joist': settings_of(pick('CJ_'))}
    sets['joist']['symbol'] = lvl_type(doc, JOIST_TYPE, 1.75 / 12, JOIST_D)
    sets['post_joist'] = dict(sets['joist'])
    sets['post_joist']['symbol'] = lvl_type(doc, POST_JOIST_TYPE, 3.5 / 12, JOIST_D)
    out = {'types': dict((k, a(v['symbol'].FamilyName + ' : ' + tname(v['symbol']))) for k, v in sets.items()),
           'justification': dict((k, [v['z'], round(v['z_off'] * 12, 3)]) for k, v in sets.items())}

    old = [e for e in framing if comment(e).startswith(REBUILD)]
    out['deleted'] = {}
    for e in old:
        g = comment(e).split('_')[0]
        out['deleted'][g] = out['deleted'].get(g, 0) + 1
        doc.Delete(e.Id)
    doc.Regenerate()

    created, beams = {}, {}
    for name, grp, p, q in members():
        s = sets[grp]
        line = DB.Line.CreateBound(to_model(p, plate), to_model(q, plate))
        fi = doc.Create.NewFamilyInstance(line, s['symbol'], doc.GetElement(s['level']), DB.Structure.StructuralType.Beam)
        DB.Structure.StructuralFramingUtils.DisallowJoinAtEnd(fi, 0)
        DB.Structure.StructuralFramingUtils.DisallowJoinAtEnd(fi, 1)
        fi.get_Parameter(DB.BuiltInParameter.Z_JUSTIFICATION).Set(s['z'])
        fi.get_Parameter(DB.BuiltInParameter.Y_JUSTIFICATION).Set(s['y'])
        fi.get_Parameter(DB.BuiltInParameter.Z_OFFSET_VALUE).Set(s['z_off'])
        fi.get_Parameter(DB.BuiltInParameter.Y_OFFSET_VALUE).Set(s['y_off'])
        fi.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).Set(name)
        fi.get_Parameter(DB.BuiltInParameter.PHASE_CREATED).Set(phase.Id)
        beams[name] = fi
        g = name.split('_')[0]
        created[g] = created.get(g, 0) + 1
    out['created'] = created
    out['joist_x'] = [n[3:] + ('*' if g == 'post_joist' else '') for n, g, _, _ in members() if g in ('joist', 'post_joist')]
    doc.Regenerate()

    # Posts: move onto their joists and fit between the joist top and the beam underside
    out['posts'] = []
    for e in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_StructuralColumns).WhereElementIsNotElementType():
        label = OLD_LABELS.get(comment(e), comment(e))
        if label not in POSTS or not in_option(e):
            continue
        X, Z, beam_name = POSTS[label]
        target = to_model((X, 0.0, Z), plate)
        here = e.Location.Point
        DB.ElementTransformUtils.MoveElement(doc, e.Id, DB.XYZ(target.X - here.X, target.Y - here.Y, 0.0))
        e.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).Set(label)
        joist = beams['CJ_%.2f' % X]
        jz = z_range_at(joist, target.X, target.Y)
        bz = z_range_at(beams[beam_name], target.X, target.Y)
        e.get_Parameter(DB.BuiltInParameter.FAMILY_BASE_LEVEL_OFFSET_PARAM).Set(jz[1] - plate)
        e.get_Parameter(DB.BuiltInParameter.FAMILY_TOP_LEVEL_OFFSET_PARAM).Set(bz[0] - plate)
        out['posts'].append({'label': label, 'id': e.Id.Value, 'on': 'CJ_%.2f' % X, 'under': beam_name,
                             'moved_in': [round((target.X - here.X) * 12, 2), round((target.Y - here.Y) * 12, 2)],
                             'joist_top': round(jz[1], 3), 'beam_bottom': round(bz[0], 3),
                             'height_in': round((bz[0] - jz[1]) * 12, 2)})
    doc.Regenerate()
    # Corner check: hips start at the outside wall corners
    out['hip_heels'] = dict((n, [round(beams[n].Location.Curve.GetEndPoint(0).X, 3),
                                 round(beams[n].Location.Curve.GetEndPoint(0).Y, 3)]) for n in ('HIP_W', 'HIP_E'))
    return out
