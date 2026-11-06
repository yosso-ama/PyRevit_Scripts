"""South grading band plus graded returns around the southwest and southeast
corners of the lower addition.

One lowering field is subtracted from the existing (survey) grade:
    z = E(x, y) - drop0 * f_out * f_along
drop0 is (existing - floor grade) at the south wall.  f_out falls from 1 at the
wall to 0 BAND_DEPTH away; along the side walls f_along falls from 1 at the
corner to 0 RETURN_LENGTH up the wall, and past the corners both fall off.
"""
from pyrevit.api import DB
from System.Collections.Generic import List
import topo_rooms as tr
import south_band as sb

BAND_DEPTH = 15.0      # ft outward from the walls to where grade meets the existing surface
RETURN_LENGTH = 12.0   # ft along each side wall over which the low grade returns to existing
ROW_STEP = 1.0
COL_STEP = 2.0
FOOTING_COVER = 0.5    # ft of soil kept over a footing that would otherwise be exposed
EXPOSED_TOL = 0.05     # ft: footings flush with grade within this are left alone
WALL_SLOPE = 0.25      # max rise/run of grade along the wall (1:4) when stepping over a footing
FOOTING_PROBE = 0.3    # ft outside the grade ring where the footing top is read


def clamp01(v):
    return max(0.0, min(1.0, v))


def option_footings(doc, topo):
    opt = topo.DesignOption.Id if topo.DesignOption else DB.ElementId.InvalidElementId
    return [e for e in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_StructuralFoundation)
            .WhereElementIsNotElementType()
            if e.DesignOption is not None and e.DesignOption.Id == opt]


def footing_top(footings, x, y):
    """Highest footing top on a vertical line at (x, y), or None."""
    best = None
    for f in footings:
        z = tr.top_z(f, x, y)
        if z is None:
            for g in f.get_Geometry(DB.Options()):
                if isinstance(g, DB.GeometryInstance):
                    line = DB.Line.CreateBound(DB.XYZ(x, y, 950.0), DB.XYZ(x, y, 1020.0))
                    for s in g.GetInstanceGeometry():
                        if isinstance(s, DB.Solid) and s.Volume > 0:
                            res = s.IntersectWithCurve(line, DB.SolidCurveIntersectionOptions())
                            for k in range(res.SegmentCount):
                                zz = res.GetCurveSegment(k).GetEndPoint(1).Z
                                z = zz if z is None else max(z, zz)
        if z is not None:
            best = z if best is None else max(best, z)
    return best


def adjusted_south(doc, topo, rooms):
    """South-wall grade points with grade raised to cover exposed footings,
    then eased along the wall so it never rises faster than WALL_SLOPE."""
    footings = option_footings(doc, topo)
    pts = tr.south_grade_points(rooms)
    raw, raised = [], []
    for x, y, zf in pts:
        top = footing_top(footings, x, y - FOOTING_PROBE)
        if top is not None and top > zf + EXPOSED_TOL:
            raw.append(top + FOOTING_COVER)
            raised.append(round(x, 2))
        else:
            raw.append(zf)
    eased = []
    for i, (x, y, zf) in enumerate(pts):
        need = max(raw[j] - WALL_SLOPE * abs(x - pts[j][0]) for j in range(len(pts)))
        eased.append((x, y, max(zf, need)))
    return eased, raised


def wall_line_from(south):
    """(xw, xe, wall_at) from south-wall grade points (x, y, z)."""
    south = sorted(south, key=lambda p: p[0])
    wall = [p for p in south if abs(p[1] - min(q[1] for q in south if abs(q[0] - p[0]) < 0.5)) < 1e-6]

    def wall_at(x):
        p = min(wall, key=lambda q: abs(q[0] - x))
        return p[1], p[2]
    return south[0][0], south[-1][0], wall_at


def side_ring(rooms):
    """Grade-ring points (x, y, nx) on the outermost west and east wall faces."""
    g = tr.WALL - tr.INSET
    outer = [(r[1] - g, r[2] + g, r[3] - g, r[4] + g) for r in rooms]
    xw, xe = min(o[0] for o in outer), max(o[1] for o in outer)
    pts, seen = [], set()
    for i, rect in enumerate(outer):
        for x, y, nx, ny in tr.ring(rect[0], rect[1], rect[2], rect[3], tr.RING_STEP):
            key = (round(x, 2), round(y, 2))
            if key in seen or any(tr.strictly_inside(x, y, o) for j, o in enumerate(outer) if j != i):
                continue
            seen.add(key)
            if ny == 0 and ((nx < 0 and abs(x - xw) < 1e-6) or (nx > 0 and abs(x - xe) < 1e-6)):
                pts.append((x, y, nx))
    return pts


class Field(object):
    """Lowering field for one design option."""

    def __init__(self, rooms, existing, south):
        self.E = existing
        self.xw, self.xe, self.wall_at = wall_line_from(south)
        self.yw_w, self.zf_w = self.wall_at(self.xw)       # southwest corner (wall line y, floor grade)
        self.yw_e, self.zf_e = self.wall_at(self.xe)       # southeast corner

    def floor_at(self, x):
        """Floor grade of the south wall for column x (clamped to the corners)."""
        return self.wall_at(min(max(x, self.xw), self.xe))[1]

    def z(self, x, y):
        e = self.E(x, y)
        if e is None:
            return None
        if x < self.xw:
            yc, out_x = self.yw_w, self.xw - x
        elif x > self.xe:
            yc, out_x = self.yw_e, x - self.xe
        else:
            yc, out_x = self.wall_at(x)[0], 0.0
        f_x = clamp01(1.0 - out_x / BAND_DEPTH)
        if y <= yc:
            f_y = clamp01(1.0 - (yc - y) / BAND_DEPTH)       # south of the wall line
        else:
            f_y = clamp01(1.0 - (y - yc) / RETURN_LENGTH)    # up along a side wall
        # Blend toward the floor grade; never below the floor or the existing grade
        z = e - max(0.0, e - self.floor_at(x)) * f_x * f_y
        if y <= yc and out_x == 0.0:
            # Where the wall grade is above existing (raised over a footing),
            # fall away from the wall no steeper than WALL_SLOPE
            z = max(z, self.floor_at(x) - WALL_SLOPE * (yc - y))
        return z

    def in_zone(self, x, y):
        """Area whose old vertices are replaced (outside the building)."""
        if not (self.xw - BAND_DEPTH - 0.5 <= x <= self.xe + BAND_DEPTH + 0.5):
            return False
        if self.xw - 0.01 < x < self.xe + 0.01:
            yw = self.wall_at(x)[0]
            return yw - BAND_DEPTH - 0.5 <= y <= yw - 0.01
        yc = self.yw_w if x <= self.xw else self.yw_e
        return yc - BAND_DEPTH - 0.5 <= y <= yc + RETURN_LENGTH + 0.5

    def grid(self):
        pts = []
        # south band (including past the ends)
        for x in tr.steps(self.xw - BAND_DEPTH, self.xe + BAND_DEPTH, COL_STEP):
            if self.xw - 0.01 < x < self.xe + 0.01:
                yc = self.wall_at(x)[0]
            else:
                yc = self.yw_w if x < self.xw else self.yw_e
            for d in tr.steps(ROW_STEP, BAND_DEPTH, ROW_STEP):
                pts.append((x, yc - d))
        # returns beside the west and east walls (from the corner line up)
        for xs, sign, yc in ((self.xw, -1.0, self.yw_w), (self.xe, 1.0, self.yw_e)):
            for d in tr.steps(ROW_STEP, BAND_DEPTH, ROW_STEP):
                for y in tr.steps(yc, yc + RETURN_LENGTH + COL_STEP, COL_STEP):
                    pts.append((xs + sign * d, y))
        out = []
        for x, y in pts:
            z = self.z(x, y)
            if z is not None:
                out.append((x, y, z))
        return out


PROBES = [('W wall 1ft out, s=%g' % s, 'w', 1.0, s) for s in (0, 3, 6, 9, 12, 15)] + \
         [('E wall 1ft out, s=%g' % s, 'e', 1.0, s) for s in (0, 3, 6, 9, 12)] + \
         [('SW diagonal %gft' % d, 'sw', d, d) for d in (1, 4, 8, 12)] + \
         [('SE diagonal %gft' % d, 'se', d, d) for d in (1, 4, 8, 12)] + \
         [('S of middle, 3ft', 's', 3.0, -50.0)]


WALL_PROBE_X = (-60.0, -54.0, -51.0, -48.0, -46.0, -44.0, -40.0, -34.0, -29.0, -26.0, -20.0)


def target_of(rooms, x, y):
    """Floor grade of the south-wall point at (x, y) before any footing adjustment."""
    for px, py, pz in tr.south_grade_points(rooms):
        if abs(px - x) < 1e-6 and abs(py - y) < 1e-6:
            return pz
    return None


def probe_xy(f, kind, a, b):
    if kind == 'w':
        return f.xw - a, f.yw_w + b
    if kind == 'e':
        return f.xe + a, f.yw_e + b
    if kind == 'sw':
        return f.xw - a, f.yw_w - b
    if kind == 'se':
        return f.xe + a, f.yw_e - b
    return b, f.wall_at(b)[0] - a


def existing_points(topo, rooms):
    """Points describing the existing grade: survey vertices outside the
    building and away from the strip right against the south wall, plus the
    side-wall grade ring (sampled from the original surface)."""
    xw, xe, wall_at = sb.wall_line(rooms)
    g = tr.WALL - tr.INSET
    outer = [(r[1] - g, r[2] + g, r[3] - g, r[4] + g) for r in rooms]
    sides = set((round(x, 2), round(y, 2)) for x, y, _ in side_ring(rooms))
    pts = []
    for v in topo.GetSlabShapeEditor().SlabShapeVertices:
        p = v.Position
        k = (round(p.X, 2), round(p.Y, 2))
        if k in sides:
            pts.append((p.X, p.Y, p.Z))
            continue
        if any(o[0] - 0.05 <= p.X <= o[1] + 0.05 and o[2] - 0.05 <= p.Y <= o[3] + 0.05 for o in outer):
            continue
        if xw - 0.5 <= p.X <= xe + 0.5:
            yw = wall_at(p.X)[0]
            if yw - sb.NEAR_WALL < p.Y < yw + 0.5:
                continue                      # strip against the south wall (old spikes)
        pts.append((p.X, p.Y, p.Z))
    return pts


def regrade(doc, option_ids=None):
    report = {}
    for topo_id, (opt_name, rooms) in sorted(tr.OPTIONS.items()):
        if option_ids is not None and topo_id not in option_ids:
            continue
        topo = doc.GetElement(tr.eid(topo_id))
        south, raised = adjusted_south(doc, topo, rooms)
        f = Field(rooms, sb.surface(existing_points(topo, rooms)), south)
        probes = [(name, probe_xy(f, k, a, b)) for name, k, a, b in PROBES]
        probes += [('wall line +0.5ft S, x=%g' % x, (x, f.wall_at(x)[0] - 0.5)) for x in WALL_PROBE_X]
        before = dict((n, tr.top_z(topo, *xy)) for n, xy in probes)

        south_xy = dict(((round(p[0], 2), round(p[1], 2)), p[2]) for p in south)
        sides = side_ring(rooms)
        editor = topo.GetSlabShapeEditor()
        removed = 0
        for v in list(editor.SlabShapeVertices):
            p = v.Position
            k = (round(p.X, 2), round(p.Y, 2))
            if k in south_xy or f.in_zone(p.X, p.Y):     # south ring is re-added at its new grade
                editor.DeletePoint(v)
                removed += 1
        # side-wall grade ring within the return: same plan spots, ramped elevations
        ramped = []
        for v in list(editor.SlabShapeVertices):
            p = v.Position
            for x, y, nx in sides:
                yc = f.yw_w if nx < 0 else f.yw_e
                if abs(p.X - x) < 0.005 and abs(p.Y - y) < 0.005 and yc < y <= yc + RETURN_LENGTH:
                    z = f.z(x, y)
                    if z is not None:
                        ramped.append((p.X, p.Y, z))
                        editor.DeletePoint(v)
                    break
        taken = set((round(v.Position.X, 2), round(v.Position.Y, 2)) for v in editor.SlabShapeVertices)
        add = []
        for x, y, z in list(south) + ramped + f.grid():
            k = (round(x, 2), round(y, 2))
            if k not in taken:
                taken.add(k)
                add.append(DB.XYZ(x, y, z))
        editor.AddPoints(List[DB.XYZ](add))
        doc.Regenerate()
        after = dict((n, tr.top_z(topo, *xy)) for n, xy in probes)
        r2 = lambda v: None if v is None else round(v, 2)
        changed = sorted(set((round(x, 1), round(z, 3)) for x, y, z in south
                             if abs(z - target_of(rooms, x, y)) > 1e-3))
        report[opt_name] = {'removed': removed, 'side_points_ramped': len(ramped), 'added': len(add),
                            'footing_raised_x': raised,
                            'wall_grade_changed (x, z)': changed[::3],
                            'corners': {'SW': [round(f.xw, 3), round(f.yw_w, 3), round(f.zf_w, 3)],
                                        'SE': [round(f.xe, 3), round(f.yw_e, 3), round(f.zf_e, 3)]},
                            'probes': [[n, r2(before[n]), r2(after[n])] for n, _ in probes]}
    return report
