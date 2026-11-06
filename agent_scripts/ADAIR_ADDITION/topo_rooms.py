"""Reshape each design option's toposolid so its top sits just below the lower
floors inside the lower rooms, and stays at existing grade outside the
foundation walls.  The grade-to-floor drop happens across the wall thickness,
which the foundation walls already cut out of the toposolid.

Rooms are given by their inside wall faces (plan, internal feet); the outside
face is the inside face pushed out by the 8" foundation wall.
"""
import math
from pyrevit.api import DB
from System import Int64
from System.Collections.Generic import List

WALL = 8.0 / 12.0
INSET = 1.0 / 12.0     # rings sit this far inside the wall, never on a wall face
RING_STEP = 1.0        # ft between points along wall faces
GRID_STEP = 2.0        # ft between points inside rooms
GRID_INSET = 0.25      # ft, room grid kept off the inside wall faces
SAMPLE_OUT = 0.35      # ft outside the outer face where existing grade is read

CLEAR = 0.125 / 12.0     # 1/8" gap so soil never sits flush on a slab (overlap warning)
SHOP_UNDER = 978.393 - CLEAR     # FFE SHOP 978.893 less 6" slab
GRAVEL_UNDER = 978.893 - CLEAR   # underside of the addition gravel floor
SHELTER_UNDER = 979.393 - CLEAR  # FFE SHELTER 980.06 less 8" (TOF SHELTER)

# Foundation walls that can cut the reshaped toposolid (tested one by one);
# the others meet adjacent walls end-on and Revit cannot resolve the cut.
CUTTING_WALLS = [1341004, 1341587, 1342726, 1343039, 1343308, 1344945, 1408251, 1412079,
                 1415601, 1416595,                                     # ORIGINAL LAYOUT
                 1410978, 1410980, 1410981, 1410982, 1410986, 1412740, 1413508, 1414780]  # PROPOSED
GRAVEL_X = -42.917       # shop slab / gravel floor joint in the PROPOSED middle room


def shop_then_gravel(x):
    return SHOP_UNDER if x < GRAVEL_X else GRAVEL_UNDER


# toposolid id -> rooms as (name, xmin, xmax, ymin, ymax, target z or f(x))
OPTIONS = {
    1445669: ('PROPOSED LAYOUT', [
        ('west shop', -80.042, -63.499, -18.812, -1.167, SHOP_UNDER),
        ('west shop south', -63.499, -58.458, -18.812, -7.167, SHOP_UNDER),
        ('middle shop / gravel', -57.792, -28.0, -17.833, -7.167, shop_then_gravel),
        ('shelter', -27.333, -12.375, -19.333, -7.167, SHELTER_UNDER)]),
    1436365: ('ORIGINAL LAYOUT', [
        ('west room', -80.042, -63.062, -19.146, -2.48, SHELTER_UNDER),
        ('west room south', -63.062, -58.75, -19.146, -4.938, SHELTER_UNDER),
        ('middle room', -58.083, -28.0, -17.833, -4.938, SHELTER_UNDER),
        ('shelter', -27.333, -12.375, -19.333, -7.375, SHELTER_UNDER)]),
}


def eid(i):
    return DB.ElementId(Int64(i))


def target_z(target, x):
    return target(x) if callable(target) else target


def steps(a, b, step):
    n = max(1, int(math.ceil((b - a) / step - 1e-9)))
    return [a + (b - a) * k / float(n) for k in range(n + 1)]


def ring(xmin, xmax, ymin, ymax, step):
    """Points around a rectangle with each point's outward normal."""
    pts = []
    for x in steps(xmin, xmax, step):
        pts.append((x, ymin, 0.0, -1.0))
        pts.append((x, ymax, 0.0, 1.0))
    for y in steps(ymin, ymax, step)[1:-1]:
        pts.append((xmin, y, -1.0, 0.0))
        pts.append((xmax, y, 1.0, 0.0))
    return pts


def strictly_inside(x, y, rect, tol=1e-3):
    xmin, xmax, ymin, ymax = rect
    return xmin + tol < x < xmax - tol and ymin + tol < y < ymax - tol


def top_z(elem, x, y):
    """Highest top of elem's solids on a vertical line at (x, y), or None."""
    line = DB.Line.CreateBound(DB.XYZ(x, y, 950.0), DB.XYZ(x, y, 1020.0))
    best = None
    for g in elem.get_Geometry(DB.Options()):
        if isinstance(g, DB.Solid) and g.Volume > 0:
            res = g.IntersectWithCurve(line, DB.SolidCurveIntersectionOptions())
            for k in range(res.SegmentCount):
                z = res.GetCurveSegment(k).GetEndPoint(1).Z
                best = z if best is None else max(best, z)
    return best


USE_GRADE_RING = True
USE_FLOOR_RING = True


def plan_points(topo, rooms):
    """(grade points outside the walls, floor points inside the rooms)."""
    if not USE_GRADE_RING:
        return [], _floor_points(rooms), 0
    grade, missing = _grade_points(topo, rooms)
    return grade, _floor_points(rooms), missing


def _grade_points(topo, rooms):
    g = WALL - INSET
    outer = [(r[1] - g, r[2] + g, r[3] - g, r[4] + g) for r in rooms]
    seen, grade, missing = set(), [], 0
    for i, rect in enumerate(outer):
        for x, y, nx, ny in ring(rect[0], rect[1], rect[2], rect[3], RING_STEP):
            key = (round(x, 2), round(y, 2))
            if key in seen or any(strictly_inside(x, y, o) for j, o in enumerate(outer) if j != i):
                continue
            seen.add(key)
            z = top_z(topo, x + nx * (INSET + SAMPLE_OUT), y + ny * (INSET + SAMPLE_OUT))
            if z is None:
                missing += 1
                continue
            grade.append((x, y, z))
    return grade, missing


def _floor_points(rooms):
    floor = []
    for (name, xmin, xmax, ymin, ymax, target) in rooms:
        # No point may sit on a wall face: Revit cannot cut coplanar geometry
        xs = steps(xmin + GRID_INSET, xmax - GRID_INSET, GRID_STEP)
        ys = steps(ymin + GRID_INSET, ymax - GRID_INSET, GRID_STEP)
        cells = [(x, y) for x in xs for y in ys]
        if USE_FLOOR_RING:
            cells += [(x, y) for x, y, _, _ in ring(xmin - INSET, xmax + INSET, ymin - INSET, ymax + INSET, RING_STEP)]
        if callable(target) and xmin < GRAVEL_X < xmax:      # sharp step at the floor joint
            cells += [(GRAVEL_X + d, y) for d in (-0.02, 0.02)
                      for y in steps(ymin + GRID_INSET, ymax - GRID_INSET, RING_STEP)]
        for x, y in set((round(x, 3), round(y, 3)) for x, y in cells):
            floor.append((x, y, target_z(target, x)))
    return floor


SOUTH_JOG_Y = -18.4    # ring points on east/west edges below this are the south-wall jogs


def south_grade_points(rooms):
    """Grade-ring points (plan x, y, room target) along the outside of the south
    foundation walls, including the short jogs where the south wall steps."""
    g = WALL - INSET
    outer = [(r[1] - g, r[2] + g, r[3] - g, r[4] + g) for r in rooms]
    west = min(o[0] for o in outer)
    east = max(o[1] for o in outer)
    pts, seen = [], set()
    for i, rect in enumerate(outer):
        for x, y, nx, ny in ring(rect[0], rect[1], rect[2], rect[3], RING_STEP):
            key = (round(x, 2), round(y, 2))
            if key in seen or any(strictly_inside(x, y, o) for j, o in enumerate(outer) if j != i):
                continue
            seen.add(key)
            jog = nx != 0 and y < SOUTH_JOG_Y and west + 0.01 < x < east - 0.01
            if ny < 0 or jog:
                pts.append((x, y, target_z(rooms[i][5], x)))
    return pts


def lower_south_grade(doc, option_ids=None):
    """Move the existing south-wall grade vertices down to the lower floor grade."""
    report = {}
    for topo_id, (opt_name, rooms) in sorted(OPTIONS.items()):
        if option_ids is not None and topo_id not in option_ids:
            continue
        topo = doc.GetElement(eid(topo_id))
        editor = topo.GetSlabShapeEditor()
        by_xy = dict(((round(v.Position.X, 2), round(v.Position.Y, 2)), v) for v in editor.SlabShapeVertices)
        wanted = south_grade_points(rooms)
        moved, missing, z_before = [], [], []
        for x, y, z in wanted:
            v = by_xy.get((round(x, 2), round(y, 2)))
            if v is None:
                missing.append([round(x, 2), round(y, 2)])
                continue
            p = v.Position
            z_before.append(p.Z)
            moved.append(DB.XYZ(p.X, p.Y, z))
            editor.DeletePoint(v)
        if moved:
            editor.AddPoints(List[DB.XYZ](moved))
        doc.Regenerate()
        report[opt_name] = {
            'moved': len(moved), 'not_found': missing,
            'grade_before_range': [round(min(z_before), 3), round(max(z_before), 3)] if z_before else None,
            'new_z_values': sorted(set(round(p.Z, 3) for p in moved)),
            'top_z': dict((k, None if top_z(topo, *v) is None else round(top_z(topo, *v), 3))
                          for k, v in SOUTH_SAMPLES.items())}
    return report


SOUTH_SAMPLES = {'1ft S of west shop wall': (-70.0, -20.5), '3ft S of west shop wall': (-70.0, -22.5),
                 '6ft S of west shop wall': (-70.0, -25.5), '1ft S of middle wall': (-50.0, -19.5),
                 '1ft S of gravel wall': (-35.0, -19.5), '1ft S of shelter wall': (-20.0, -21.0),
                 'west shop inside': (-70.0, -10.0), 'outside west wall': (-82.0, -10.0)}


# Locations checked before and after (plan x, y)
SAMPLES = {'west shop': (-70.0, -10.0), 'middle shop': (-50.0, -12.0), 'gravel area': (-35.0, -12.0),
           'shelter': (-20.0, -13.0), 'notch': (-61.0, -4.0), 'north crawl': (-70.0, 2.0),
           'outside south': (-70.0, -25.0), 'outside east': (-5.0, -12.0),
           'just outside S wall': (-70.0, -20.2), 'just outside shelter E': (-11.2, -12.0)}


def option_cutters(doc, topo):
    """New foundation walls, footings and floors in the toposolid's design option."""
    opt = topo.DesignOption.Id if topo.DesignOption else DB.ElementId.InvalidElementId
    ids = []
    for cat in (DB.BuiltInCategory.OST_Walls,):
        for e in DB.FilteredElementCollector(doc).OfCategory(cat).WhereElementIsNotElementType():
            if e.DesignOption is None or e.DesignOption.Id != opt:
                continue
            if cat == DB.BuiltInCategory.OST_Walls and not e.Name.startswith('FOUNDATION'):
                continue
            ids.append(e.Id)
    return ids


def rejoin(doc, topo, candidate_ids):
    """Join each candidate that still intersects the soil, with it cutting the toposolid."""
    if not candidate_ids:
        return [], []
    hits = DB.FilteredElementCollector(doc, List[DB.ElementId](candidate_ids)) \
        .WherePasses(DB.ElementIntersectsElementFilter(topo)).ToElementIds()
    joined, failed = [], []
    for i in hits:
        e = doc.GetElement(i)
        try:
            DB.JoinGeometryUtils.JoinGeometry(doc, e, topo)
            if not DB.JoinGeometryUtils.IsCuttingElementInJoin(doc, e, topo):
                DB.JoinGeometryUtils.SwitchJoinOrder(doc, e, topo)
            joined.append(i.Value)
        except Exception as ex:
            failed.append([i.Value, str(ex)[:100]])
    return joined, failed


def reshape(doc, rejoin_walls=True, only=None, release_joins=True, option_ids=None):
    report = {}
    for topo_id, (opt_name, rooms) in sorted(OPTIONS.items()):
        if option_ids is not None and topo_id not in option_ids:
            continue
        topo = doc.GetElement(eid(topo_id))
        before = dict((k, top_z(topo, *v)) for k, v in SAMPLES.items())
        old_joins = [i.Value for i in DB.JoinGeometryUtils.GetJoinedElements(doc, topo)]
        if release_joins:
            for i in list(DB.JoinGeometryUtils.GetJoinedElements(doc, topo)):
                DB.JoinGeometryUtils.UnjoinGeometry(doc, doc.GetElement(i), topo)
            for i in list(DB.SolidSolidCutUtils.GetCuttingSolids(topo)):
                DB.SolidSolidCutUtils.RemoveCutBetweenSolids(doc, topo, doc.GetElement(i))
            doc.Regenerate()
        grade, floor, missing = plan_points(topo, rooms)
        editor = topo.GetSlabShapeEditor()
        n0 = editor.SlabShapeVertices.Size
        # Revit needs every point distinct in plan, including from existing vertices
        taken = set((round(v.Position.X, 2), round(v.Position.Y, 2)) for v in editor.SlabShapeVertices)
        unique = []
        for x, y, z in grade + floor:
            key = (round(x, 2), round(y, 2))
            if key not in taken:
                taken.add(key)
                unique.append(DB.XYZ(x, y, z))
        pts = List[DB.XYZ](unique)
        editor.AddPoints(pts)
        doc.Regenerate()
        cutters = option_cutters(doc, topo) if rejoin_walls else []
        if only is not None:
            cutters = [c for c in cutters if c.Value in only]
        joined, join_failed = rejoin(doc, topo, cutters)
        doc.Regenerate()
        after = dict((k, top_z(topo, *v)) for k, v in SAMPLES.items())
        report[opt_name] = {
            'toposolid': topo_id, 'points_added': len(unique),
            'joins_before': old_joins, 'joins_after': joined, 'join_failures': join_failed,
            'grade_points': len(grade), 'floor_points': len(floor),
            'grade_samples_missing': missing, 'vertices_before': n0,
            'vertices_after': topo.GetSlabShapeEditor().SlabShapeVertices.Size,
            'top_z': dict((k, [None if before[k] is None else round(before[k], 3),
                               None if after[k] is None else round(after[k], 3)]) for k in SAMPLES)}
    return report
