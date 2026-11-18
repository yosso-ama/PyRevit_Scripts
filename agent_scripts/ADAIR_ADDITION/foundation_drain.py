"""Perforated foundation drain runs for the PROPOSED addition footings.

Sets up a 4" PERFORATED PVC pipe type (duplicate of PVC - DWV, so it keeps the PVC
DWV routing preferences) and a FOUNDATION DRAIN piping system (duplicate of Other,
abbreviation PD, dashed line).

Runs come from detail lines drawn along the drain centreline: connected lines form
one run, separate groups are separate runs.  Each run slopes at no less than
MIN_SLOPE toward whichever end leaves the shallower outlet, its invert never drops
below the bottom of the adjacent footing, and its pipes are joined with elbows.
"""
from pyrevit.api import DB
from Autodesk.Revit.DB import Plumbing
from System import Int64

PIPE_TYPE_SRC, PIPE_TYPE = 'PVC - DWV', '4" PERFORATED PVC'
SYSTEM_SRC, SYSTEM = 'Other', 'FOUNDATION DRAIN'
ABBREV = 'PD'
LINE_PATTERNS = ('Dash', 'Hidden', 'Dash 1/8"', 'Dashed')
LEVEL = 'TOF SHOP'
PHASE = 'Adair Addition'
DIAMETER = 4.0 / 12
MIN_SLOPE = 0.125 / 12
COMMENT = 'FOUNDATION DRAIN'
JOIN_TOL = 0.05
SAMPLE_REACH = (0.5, 1.0, 1.5, 2.0, 2.5)
FOOTINGS = [1410999, 1411001, 1411003, 1411004, 1411005, 1424065, 1425583, 1428605, 1433031, 1411006, 1411014, 1411015]


def tname(e):
    p = e.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
    return p.AsString() if p else None


def by_name(doc, cls, name):
    for t in DB.FilteredElementCollector(doc).OfClass(cls):
        if tname(t) == name:
            return t
    return None


def setup_types(doc):
    made = []
    pt = by_name(doc, Plumbing.PipeType, PIPE_TYPE)
    if pt is None:
        pt = by_name(doc, Plumbing.PipeType, PIPE_TYPE_SRC).Duplicate(PIPE_TYPE)
        pt.get_Parameter(DB.BuiltInParameter.ALL_MODEL_TYPE_COMMENTS).Set('PERFORATED FOUNDATION DRAIN, ASTM D2729 OR EQUAL')
        made.append(PIPE_TYPE)
    st = by_name(doc, Plumbing.PipingSystemType, SYSTEM)
    if st is None:
        st = by_name(doc, Plumbing.PipingSystemType, SYSTEM_SRC).Duplicate(SYSTEM)
        st.get_Parameter(DB.BuiltInParameter.RBS_SYSTEM_ABBREVIATION_PARAM).Set(ABBREV)
        pats = dict((lp.Name, lp) for lp in DB.FilteredElementCollector(doc).OfClass(DB.LinePatternElement))
        for n in LINE_PATTERNS:
            if n in pats:
                st.LinePatternId = pats[n].Id
                break
        made.append(SYSTEM)
    return pt, st, made


def solids_of(e):
    out = []
    for g in e.get_Geometry(DB.Options()):
        for s in ([g] if isinstance(g, DB.Solid) else (list(g.GetInstanceGeometry()) if isinstance(g, DB.GeometryInstance) else [])):
            if isinstance(s, DB.Solid) and s.Volume > 1e-6:
                out.append(s)
    return out


def footing_solids(doc):
    sol = []
    for i in FOOTINGS:
        e = doc.GetElement(DB.ElementId(Int64(i)))
        if e is not None:
            sol += solids_of(e)
    return sol


def footing_bottom(solids, x, y):
    """Lowest footing bottom on a vertical line through (x, y), or None."""
    line = DB.Line.CreateBound(DB.XYZ(x, y, 960.0), DB.XYZ(x, y, 1000.0))
    best = None
    for s in solids:
        r = s.IntersectWithCurve(line, DB.SolidCurveIntersectionOptions())
        for k in range(r.SegmentCount):
            z = r.GetCurveSegment(k).GetEndPoint(0).Z
            best = z if best is None else min(best, z)
    return best


def chains_from_curves(curves):
    """Group straight plan segments into connected chains of (x, y) points."""
    segs = []
    for c in curves:
        if isinstance(c, DB.Line):
            p, q = c.GetEndPoint(0), c.GetEndPoint(1)
            segs.append([(p.X, p.Y), (q.X, q.Y)])
    near = lambda a, b: abs(a[0] - b[0]) < JOIN_TOL and abs(a[1] - b[1]) < JOIN_TOL
    chains = []
    while segs:
        chain = segs.pop(0)
        grown = True
        while grown:
            grown = False
            for s in list(segs):
                if near(chain[-1], s[0]):
                    chain.append(s[1])
                elif near(chain[-1], s[1]):
                    chain.append(s[0])
                elif near(chain[0], s[1]):
                    chain.insert(0, s[0])
                elif near(chain[0], s[0]):
                    chain.insert(0, s[1])
                else:
                    continue
                segs.remove(s)
                grown = True
        chains.append(chain)
    return chains


def seg_len(a, b):
    return ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5


def profile(solids, path):
    """(chainage, adjacent footing bottom) every foot along path; the footing is
    found by stepping sideways from the centreline, either side."""
    pts, s0 = [], 0.0
    for a, b in zip(path, path[1:]):
        L = seg_len(a, b)
        ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        n = max(1, int(L))
        for k in range(n + 1):
            t = L * k / n
            px, py = a[0] + ux * t, a[1] + uy * t
            bot = None
            for d in SAMPLE_REACH:
                for sgn in (1, -1):
                    bot = footing_bottom(solids, px + uy * d * sgn, py - ux * d * sgn)
                    if bot is not None:
                        break
                if bot is not None:
                    break
            pts.append((s0 + t, bot))
        s0 += L
    return pts, s0


def plan_run(solids, path):
    """Pick the flow direction with the shallower outlet; return path ordered high
    to low, its profile, total length and high-end invert."""
    best = None
    for p in (path, list(reversed(path))):
        prof, total = profile(solids, p)
        known = [(s, b) for s, b in prof if b is not None]
        if not known:
            continue
        start = max(b + MIN_SLOPE * s for s, b in known)
        low = start - MIN_SLOPE * total
        if best is None or low > best[4]:
            best = (p, prof, total, start, low)
    return best


def lay_run(doc, st, pt, level, phase, name, path, prof, total, start, outlet=None, outlet_type=None, low=None):
    """Pipes along path (perforated), then an optional solid outlet pipe from the
    low end to outlet (x, y), all at one continuous slope: MIN_SLOPE, or the slope
    that reaches invert low at the far end when low is given."""
    r = DIAMETER / 2.0
    pts = list(path) + ([outlet] if outlet else [])
    slope = MIN_SLOPE if low is None else (start - low) / sum(seg_len(a, b) for a, b in zip(pts, pts[1:]))
    inv = lambda s: start - slope * s
    segs, s0, pipes = [], 0.0, []
    for i, (a, b) in enumerate(zip(pts, pts[1:])):
        L = seg_len(a, b)
        is_outlet = outlet is not None and i == len(pts) - 2
        ptype = outlet_type if is_outlet else pt
        p = Plumbing.Pipe.Create(doc, st.Id, ptype.Id, level.Id,
                                 DB.XYZ(a[0], a[1], inv(s0) + r), DB.XYZ(b[0], b[1], inv(s0 + L) + r))
        p.get_Parameter(DB.BuiltInParameter.RBS_PIPE_DIAMETER_PARAM).Set(DIAMETER)
        p.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).Set(
            '{} - {}{}'.format(COMMENT, name, ' OUTLET' if is_outlet else ''))
        p.get_Parameter(DB.BuiltInParameter.PHASE_CREATED).Set(phase.Id)
        pipes.append(p)
        segs.append([tname(ptype), round(s0, 2), round(L, 2), round(inv(s0), 3), round(inv(s0 + L), 3)])
        s0 += L
    total_all = s0
    doc.Regenerate()
    elbows, unions, fails = 0, 0, []
    for a, b in zip(pipes, pipes[1:]):
        end = a.Location.Curve.GetEndPoint(1)
        ca = [c for c in a.ConnectorManager.Connectors if c.Origin.DistanceTo(end) < 1e-3][0]
        cb = [c for c in b.ConnectorManager.Connectors if c.Origin.DistanceTo(end) < 1e-3][0]
        straight = a.Location.Curve.Direction.DotProduct(b.Location.Curve.Direction) > 0.9999
        try:
            if straight:
                doc.Create.NewUnionFitting(ca, cb)
                unions += 1
            else:
                doc.Create.NewElbowFitting(ca, cb)
                elbows += 1
        except Exception as ex:
            fails.append(str(ex)[:100])
    return {'name': name, 'high_end_xy': [round(path[0][0], 2), round(path[0][1], 2)],
            'outlet_xy': [round(pts[-1][0], 2), round(pts[-1][1], 2)],
            'slope_in_per_ft': round(slope * 12, 3), 'unions': unions,
            'perforated_length_ft': round(total, 2), 'total_length_ft': round(total_all, 2),
            'invert_high': round(start, 3), 'invert_end_of_perforated': round(inv(total), 3),
            'invert_outlet': round(inv(total_all), 3),
            'segments [type, chainage, length, inv_start, inv_end]': segs, 'elbows': elbows, 'elbow_failures': fails,
            'samples_without_footing': [round(s, 1) for s, b in prof if b is None],
            'pipe_ids': [p.Id.Value for p in pipes],
            'design_option': pipes[0].DesignOption.Name if pipes and pipes[0].DesignOption else 'Main Model'}


def project_z(doc, elevation, datum='FFE (EXISTING)'):
    """Internal Z of a project elevation measured from the datum level (= 0)."""
    lvl = [l for l in DB.FilteredElementCollector(doc).OfClass(DB.Level) if l.Name == datum][0]
    return lvl.ProjectElevation + elevation


def run(doc, curves, view, names=None, high_inverts=None, high_ends=None, outlets=None, low_inverts=None):
    """Lay one drain run per connected group of curves.  Runs are named by their
    position across the view, left to right, unless names are given.  Per run name:
    high_inverts gives the high-end invert as a project elevation (ft from FFE
    (EXISTING)), otherwise the lowest invert that keeps the run at or above the
    adjacent footing bottoms; high_ends gives an (x, y) near the end that should be
    high, otherwise the direction with the shallower outlet; outlets gives the (x, y)
    of a solid outlet pipe from the low end to daylight; low_inverts gives the
    invert at the far end (project elevation), which sets the slope instead of
    MIN_SLOPE."""
    pt, st, made = setup_types(doc)
    level = [l for l in DB.FilteredElementCollector(doc).OfClass(DB.Level) if l.Name == LEVEL][0]
    phase = [p for p in doc.Phases if p.Name == PHASE][0]
    solids = footing_solids(doc)
    chains = chains_from_curves(curves)
    rd = view.RightDirection
    chains.sort(key=lambda c: sum(p[0] * rd.X + p[1] * rd.Y for p in c) / len(c))
    names = names or (['LEFT', 'RIGHT'] if len(chains) == 2 else ['RUN %d' % (i + 1) for i in range(len(chains))])
    runs = []
    solid = by_name(doc, Plumbing.PipeType, PIPE_TYPE_SRC)
    for name, chain in zip(names, chains):
        if high_ends and name in high_ends:
            hx, hy = high_ends[name]
            if seg_len(chain[-1], (hx, hy)) < seg_len(chain[0], (hx, hy)):
                chain = list(reversed(chain))
            prof, total = profile(solids, chain)
            known = [(s, b) for s, b in prof if b is not None]
            plan = (chain, prof, total, max(b + MIN_SLOPE * s for s, b in known) if known else None, None)
        else:
            plan = plan_run(solids, chain)
        if plan is None or (plan[3] is None and not (high_inverts and name in high_inverts)):
            runs.append({'name': name, 'error': 'no footing found beside this run'})
            continue
        path, prof, total, start, low = plan
        if high_inverts and name in high_inverts:
            start = project_z(doc, high_inverts[name])
        out = outlets.get(name) if outlets else None
        low = project_z(doc, low_inverts[name]) if low_inverts and name in low_inverts else None
        runs.append(lay_run(doc, st, pt, level, phase, name, path, prof, total, start, out, solid, low))
    doc.Regenerate()
    return {'types_created': made, 'pipe_type': [pt.Id.Value, PIPE_TYPE], 'system': [st.Id.Value, SYSTEM],
            'line_pattern': doc.GetElement(st.LinePatternId).Name if st.LinePatternId.Value > 0 else None,
            'slope_in_per_ft': round(MIN_SLOPE * 12, 4), 'runs': runs}


# Runs as built in ADAIR_ADDITION.rvt (2026-11-18), from the detail lines in FFE SHELTER.
# Elevations: 'rel' = project elevation from FFE (EXISTING) = 0, 'abs' = survey elevation.
SAVED_RUNS = [
    {'name': 'LEFT',
     'path': [(-59.052, -4.186), (-62.135, -4.186), (-62.135, 0.0), (-81.469, 0.0), (-81.469, -22.417)],
     'high': ('rel', -(7 + 10 / 12.0)), 'low': None,
     'outlet': (-81.469 - 18.5, -22.417)},
    {'name': 'RIGHT',
     'path': [(-26.839, -5.833), (-10.839, -5.833), (-10.839, -20.92)],
     'high': ('abs', 981.0), 'low': ('abs', 979.5),
     'outlet': (-10.839, -28.333)},
]
CHECK_FOOTINGS = 'NEW WALL FOOTING'


def existing_drains(doc):
    return [p for p in DB.FilteredElementCollector(doc).OfClass(Plumbing.Pipe)
            if (p.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).AsString() or '').startswith(COMMENT)]


def footing_check(doc, runs=SAVED_RUNS, reach=4.0):
    """Fraction of path sample points with a CHECK_FOOTINGS footing within reach
    (plan), so a file whose footings sit elsewhere is caught before laying pipe."""
    boxes = []
    for e in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_StructuralFoundation).WhereElementIsNotElementType():
        t = doc.GetElement(e.GetTypeId())
        if t is not None and tname(t) == CHECK_FOOTINGS:
            bb = e.get_BoundingBox(None)
            if bb:
                boxes.append(bb)
    hit = n = 0
    for r in runs:
        for a, b in zip(r['path'], r['path'][1:]):
            for k in range(5):
                x = a[0] + (b[0] - a[0]) * k / 4.0
                y = a[1] + (b[1] - a[1]) * k / 4.0
                n += 1
                if any(bb.Min.X - reach <= x <= bb.Max.X + reach and bb.Min.Y - reach <= y <= bb.Max.Y + reach for bb in boxes):
                    hit += 1
    return hit, n, len(boxes)


def lay_saved(doc, runs=SAVED_RUNS):
    """Lay the saved runs into doc (call inside a transaction).  Elevations given
    as 'abs' are survey elevations; they are converted with this file's FFE datum."""
    ffe = project_z(doc, 0.0)
    view = doc.ActiveView
    out = []
    for r in runs:
        curves = [DB.Line.CreateBound(DB.XYZ(a[0], a[1], 0), DB.XYZ(b[0], b[1], 0)) for a, b in zip(r['path'], r['path'][1:])]
        rel = lambda v: v[1] if v[0] == 'rel' else v[1] - ffe
        res = run(doc, curves, view, names=[r['name']],
                  high_inverts={r['name']: rel(r['high'])},
                  low_inverts={r['name']: rel(r['low'])} if r['low'] else None,
                  high_ends={r['name']: r['path'][0]},
                  outlets={r['name']: r['outlet']} if r['outlet'] else None)
        out.append(res)
    return out
