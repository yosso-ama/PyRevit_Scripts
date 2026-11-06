"""Grade a band south of the lower addition: from the floor grade at the south
foundation wall up to the existing (survey) grade BAND_DEPTH ft away, tapering
out past each end of the building.  Replaces the survey points inside the band
so long triangles no longer fan from them down to the wall (the "ridges").
"""
from pyrevit.api import DB
from System.Collections.Generic import List
import topo_rooms as tr

BAND_DEPTH = 15.0     # ft from the south wall to where grade meets the existing surface
ROW_STEP = 1.0        # ft between band rows
COL_STEP = 2.0        # ft between band columns
END_TAPER = 10.0      # ft past each end of the building over which the lowering fades out

# Original survey points of the toposolid (before any grading by this script)
SURVEY = [(25.689, -106.553, 979.56), (-108.131, -44.152, 979.56), (-49.37, -34.176, 983.56),
          (-30.169, -31.694, 985.06), (-63.621, -30.098, 983.56), (-14.58, -29.564, 985.06),
          (-82.662, -27.863, 982.56), (8.751, -21.324, 984.56), (-98.696, -17.07, 981.56),
          (-28.005, -2.5, 985.893), (-11.708, -2.5, 986.06), (29.382, -0.805, 985.56),
          (-99.777, -0.094, 983.06), (-58.083, 0.0, 985.06), (-45.833, 0.0, 985.143),
          (-11.708, 0.0, 986.06), (-0.174, 0.0, 986.06), (0.0, 0.0, 986.06), (0.0, 0.221, 986.06),
          (-45.833, 3.5, 985.56), (-28.005, 3.5, 985.56), (-80.708, 5.5, 985.56), (-80.606, 5.5, 985.56),
          (-58.083, 5.5, 985.56), (-80.708, 5.737, 985.56), (-106.358, 6.633, 982.56),
          (-80.708, 31.591, 986.727), (-80.708, 31.812, 986.727), (-58.083, 31.812, 986.893),
          (-105.456, 32.456, 984.56), (-45.25, 39.5, 987.227), (-30.75, 39.5, 987.227),
          (-11.833, 39.75, 987.227), (-0.064, 39.75, 987.06), (0.0, 39.75, 986.727),
          (-58.083, 41.062, 987.06), (-45.25, 41.062, 987.227), (-30.75, 43.583, 987.227),
          (-24.208, 43.583, 987.227), (-24.208, 45.583, 987.227), (-11.833, 45.583, 987.227),
          (-103.627, 84.83, 987.227), (32.373, 84.83, 987.227)]


NEAR_WALL = 1.5       # ft: survey points this close south of the wall are not trusted as existing grade


def delaunay(pts):
    """Bowyer-Watson triangulation of plan points; returns index triples."""
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    span = max(max(xs) - min(xs), max(ys) - min(ys)) * 20.0
    cx, cy = (max(xs) + min(xs)) / 2.0, (max(ys) + min(ys)) / 2.0
    work = list(pts) + [(cx - span, cy - span, 0), (cx + span, cy - span, 0), (cx, cy + span, 0)]
    n = len(pts)
    tris = [(n, n + 1, n + 2)]

    def circum(t):
        (ax, ay), (bx, by), (qx, qy) = [(work[i][0], work[i][1]) for i in t]
        d = 2.0 * (ax * (by - qy) + bx * (qy - ay) + qx * (ay - by))
        ux = ((ax * ax + ay * ay) * (by - qy) + (bx * bx + by * by) * (qy - ay) + (qx * qx + qy * qy) * (ay - by)) / d
        uy = ((ax * ax + ay * ay) * (qx - bx) + (bx * bx + by * by) * (ax - qx) + (qx * qx + qy * qy) * (bx - ax)) / d
        return ux, uy, (ax - ux) ** 2 + (ay - uy) ** 2

    for i in range(n):
        px, py = work[i][0], work[i][1]
        bad = [t for t in tris if (lambda c: (px - c[0]) ** 2 + (py - c[1]) ** 2 < c[2])(circum(t))]
        edges = {}
        for t in bad:
            for e in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                k = tuple(sorted(e))
                edges[k] = edges.get(k, 0) + 1
        tris = [t for t in tris if t not in bad]
        tris += [(a, b, i) for (a, b), c in edges.items() if c == 1]
    return [t for t in tris if max(t) < n]


def surface(survey):
    """Linear-interpolating function over a Delaunay triangulation of survey points."""
    tris = delaunay(survey)

    def z_at(x, y):
        return survey_z(survey, tris, x, y)
    return z_at


def survey_z(survey, tris, x, y):
    """Grade at (x, y) from a survey triangulation, or None outside it."""
    for a, b, c in tris:
        (x1, y1, z1), (x2, y2, z2), (x3, y3, z3) = survey[a], survey[b], survey[c]
        d = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
        if abs(d) < 1e-12:
            continue
        l1 = ((y2 - y3) * (x - x3) + (x3 - x2) * (y - y3)) / d
        l2 = ((y3 - y1) * (x - x3) + (x1 - x3) * (y - y3)) / d
        l3 = 1.0 - l1 - l2
        if min(l1, l2, l3) >= -1e-9:
            return l1 * z1 + l2 * z2 + l3 * z3
    return None


def wall_line(rooms):
    """(xw, xe, wall_at) for the south grade ring of one option."""
    south = sorted(tr.south_grade_points(rooms), key=lambda p: p[0])
    wall = [p for p in south if abs(p[1] - min(q[1] for q in south if abs(q[0] - p[0]) < 0.5)) < 1e-6]

    def wall_at(x):
        """(wall line y, floor grade) of the south ring point nearest in x."""
        p = min(wall, key=lambda q: abs(q[0] - x))
        return p[1], p[2]
    return south[0][0], south[-1][0], wall_at


def option_survey(topo, rooms):
    """The toposolid's own survey points: vertices this script did not add,
    away from the building and the strip right against the south wall."""
    xw, xe, wall_at = wall_line(rooms)
    g = tr.WALL - tr.INSET
    outer = [(r[1] - g, r[2] + g, r[3] - g, r[4] + g) for r in rooms]
    pts = []
    for v in topo.GetSlabShapeEditor().SlabShapeVertices:
        p = v.Position
        if any(o[0] - 0.05 <= p.X <= o[1] + 0.05 and o[2] - 0.05 <= p.Y <= o[3] + 0.05 for o in outer):
            continue                                     # in the building or on its grade ring
        if xw - 0.5 <= p.X <= xe + 0.5 and p.Y > wall_at(p.X)[0] - NEAR_WALL:
            continue                                     # against the south wall
        pts.append((p.X, p.Y, p.Z))
    return pts


def band_for(rooms, existing):
    """Band points and the region they cover, for one design option.
    existing(x, y) gives the option's existing grade."""
    south = sorted(tr.south_grade_points(rooms), key=lambda p: p[0])
    xw, xe, wall_at = wall_line(rooms)
    pts = []
    for x in tr.steps(xw - END_TAPER, xe + END_TAPER, COL_STEP):
        yw, zf = wall_at(x)
        outside = max(xw - x, x - xe, 0.0)
        w = max(0.0, 1.0 - outside / END_TAPER)
        for d in tr.steps(ROW_STEP, BAND_DEPTH, ROW_STEP):
            y = yw - d
            e = existing(x, y)
            if e is None:
                continue
            graded = zf + (e - zf) * min(1.0, d / BAND_DEPTH)
            pts.append((x, y, e - (e - graded) * w))

    def in_band(x, y):
        """South of the wall grade line, within the band (old vertices here are replaced)."""
        if not (xw - END_TAPER - 0.5 <= x <= xe + END_TAPER + 0.5):
            return False
        yw, _ = wall_at(x)
        return yw - BAND_DEPTH - 0.5 <= y <= yw - 0.01

    keep = set((round(p[0], 2), round(p[1], 2)) for p in south)
    return pts, in_band, keep


PROFILE_X = (-75.0, -61.0, -50.0, -35.0, -20.0, -14.0, -85.0, -6.0)


def profile(topo, x, yw):
    return [None if tr.top_z(topo, x, yw - d) is None else round(tr.top_z(topo, x, yw - d), 2)
            for d in (0.5, 1.5, 3, 5, 8, 11, 14, 17)]


def regrade(doc, option_ids=None):
    report = {}
    for topo_id, (opt_name, rooms) in sorted(tr.OPTIONS.items()):
        if option_ids is not None and topo_id not in option_ids:
            continue
        topo = doc.GetElement(tr.eid(topo_id))
        survey = option_survey(topo, rooms)
        pts, in_band, keep = band_for(rooms, surface(survey))
        south = tr.south_grade_points(rooms)
        yw_of = lambda x: min(south, key=lambda q: abs(q[0] - x))[1]
        before = dict((x, profile(topo, x, yw_of(x))) for x in PROFILE_X)
        editor = topo.GetSlabShapeEditor()
        removed = 0
        for v in list(editor.SlabShapeVertices):
            p = v.Position
            if in_band(p.X, p.Y) and (round(p.X, 2), round(p.Y, 2)) not in keep:
                editor.DeletePoint(v)
                removed += 1
        taken = set((round(v.Position.X, 2), round(v.Position.Y, 2)) for v in editor.SlabShapeVertices)
        add = []
        for x, y, z in pts:
            k = (round(x, 2), round(y, 2))
            if k not in taken:
                taken.add(k)
                add.append(DB.XYZ(x, y, z))
        editor.AddPoints(List[DB.XYZ](add))
        doc.Regenerate()
        after = dict((x, profile(topo, x, yw_of(x))) for x in PROFILE_X)
        report[opt_name] = {'survey_points': len(survey), 'removed': removed, 'added': len(add),
                            'profile_d': [0.5, 1.5, 3, 5, 8, 11, 14, 17],
                            'profiles': dict(('x=%g' % x, {'before': before[x], 'after': after[x]})
                                             for x in PROFILE_X)}
    return report
