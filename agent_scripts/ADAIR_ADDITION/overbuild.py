"""Overframe (California framing) where the PROPOSED sunroom roof runs onto the
existing house roof: extend the ridge north until it lands on the existing roof,
continue the common rafters at 24" o.c. past the house wall as California jacks,
trim every rafter whose heel would dive into the existing roof so it seats on a
1 1/2" sleeper on top of the existing roof, and add a flat 2x8 sleeper (valley
board) under the trimmed seats on each side.
"""
import math
from pyrevit.api import DB
from System import Int64
import sunroom_v3 as s3

EXISTING_ROOF = 1369939
SLEEPER_T = 1.5 / 12             # sleeper thickness under the rafter seats
SLEEPER_TYPE = ('Dimension Lumber', '2x8')
RAFTER_D, RIDGE_D = 7.25 / 12, 11.25 / 12
THETA = math.atan(s3.PITCH)
OVER_STEP = s3.RAFTER_SPACING    # California jacks continue at 24" o.c. past the house wall
MIN_RAFTER = 1.0                 # ft: skip California jacks shorter than this


def eid(i):
    return DB.ElementId(Int64(i))


def solids(e):
    return s3.solids(e)


def roof_top(roof_solids, x, y):
    """Top of the existing roof on a vertical line through (x, y), or None."""
    line = DB.Line.CreateBound(DB.XYZ(x, y, 950.0), DB.XYZ(x, y, 1030.0))
    best = None
    for s in roof_solids:
        r = s.IntersectWithCurve(line, DB.SolidCurveIntersectionOptions())
        for k in range(r.SegmentCount):
            z = r.GetCurveSegment(k).GetEndPoint(1).Z
            best = z if best is None else max(best, z)
    return best


def clearance(roof_solids, top, low, t, z_off, half_v):
    """Gap between the member's underside and the sleeper top at parameter t
    (0 = top end, 1 = low end) along the location line top -> low."""
    p = top + (low - top) * t
    r = roof_top(roof_solids, p.X, p.Y)
    if r is None:
        return 1e9, p
    return (p.Z + z_off - half_v) - (r + SLEEPER_T), p


def seat_point(roof_solids, top, low, z_off, half_v, steps=200):
    """First point going from top toward low where the member lands on the
    sleeper; None if it never does."""
    prev_t, prev_g = 0.0, clearance(roof_solids, top, low, 0.0, z_off, half_v)[0]
    if prev_g <= 0:
        return top, 0.0
    for i in range(1, steps + 1):
        t = i / float(steps)
        g = clearance(roof_solids, top, low, t, z_off, half_v)[0]
        if g <= 0:
            lo, hi = prev_t, t
            for _ in range(30):
                mid = (lo + hi) / 2.0
                if clearance(roof_solids, top, low, mid, z_off, half_v)[0] > 0:
                    lo = mid
                else:
                    hi = mid
            return top + (low - top) * hi, hi
        prev_t, prev_g = t, g
    return None, None


def placement(e):
    return s3.settings_of(e)


def new_beam(doc, line, sets, name, phase):
    fi = doc.Create.NewFamilyInstance(line, sets['symbol'], doc.GetElement(sets['level']),
                                      DB.Structure.StructuralType.Beam)
    DB.Structure.StructuralFramingUtils.DisallowJoinAtEnd(fi, 0)
    DB.Structure.StructuralFramingUtils.DisallowJoinAtEnd(fi, 1)
    fi.get_Parameter(DB.BuiltInParameter.Z_JUSTIFICATION).Set(sets['z'])
    fi.get_Parameter(DB.BuiltInParameter.Y_JUSTIFICATION).Set(sets['y'])
    fi.get_Parameter(DB.BuiltInParameter.Z_OFFSET_VALUE).Set(sets['z_off'])
    fi.get_Parameter(DB.BuiltInParameter.Y_OFFSET_VALUE).Set(sets['y_off'])
    fi.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).Set(name)
    fi.get_Parameter(DB.BuiltInParameter.PHASE_CREATED).Set(phase.Id)
    return fi


def run(doc):
    level = [l for l in DB.FilteredElementCollector(doc).OfClass(DB.Level) if l.Name == 'TOP OF WALLS'][0]
    plate = level.ProjectElevation
    phase = [p for p in doc.Phases if p.Name == s3.PHASE][0]
    roof_solids = solids(doc.GetElement(eid(EXISTING_ROOF)))
    framing = dict((s3.comment(e), e) for e in DB.FilteredElementCollector(doc)
                   .OfCategory(DB.BuiltInCategory.OST_StructuralFraming).WhereElementIsNotElementType()
                   if s3.in_option(e) and s3.comment(e).startswith(s3.REBUILD))
    out = {'trimmed': [], 'added': [], 'ridge': None, 'sleepers': []}
    rafter_set = placement(framing['COMMON_W_%.2f' % s3.LENGTH])
    half_v_raf = RAFTER_D / 2.0 / math.cos(THETA)

    # 1. Ridge: extend north from the house wall until it lands on the existing roof
    ridge = framing['RIDGE']
    rset = placement(ridge)
    rc = ridge.Location.Curve
    apex, south = rc.GetEndPoint(0), rc.GetEndPoint(1)
    far = DB.XYZ(south.X, south.Y + 20.0, south.Z)
    seat, _ = seat_point(roof_solids, south, far, rset['z_off'], RIDGE_D / 2.0)
    if seat is not None and seat.DistanceTo(south) > 0.05:
        ridge.Location.Curve = DB.Line.CreateBound(apex, seat)
        out['ridge'] = {'extended_ft': round(seat.Y - south.Y, 3), 'new_end_y': round(seat.Y, 3)}
    ridge_end_y = (seat or south).Y
    ridge_end_z = s3.Y0 and (ridge_end_y - s3.Y0)          # script Z of the ridge end

    # 2. California jacks: continue the commons past the house wall at 24" o.c.
    z = s3.LENGTH + OVER_STEP
    while z < ridge_end_z - 0.25:
        for side, x0 in (('W', 0.0), ('E', s3.WIDTH)):
            name = 'OVER_%s_%.2f' % (side, z)
            top = s3.to_model((s3.RUN, s3.H_RIDGE, z), plate)
            low = s3.to_model((x0, 0.0, z), plate)
            fi = new_beam(doc, DB.Line.CreateBound(low, top), rafter_set, name, phase)
            framing[name] = fi
            out['added'].append(name)
        z += OVER_STEP
    doc.Regenerate()

    # 3. Trim every rafter that dives into the existing roof so it seats on the sleeper
    seats = {'W': [], 'E': []}
    for name in sorted(framing):
        if not name.startswith(('COMMON_', 'OVER_', 'JACK_', 'KING_')):
            continue
        e = framing[name]
        c = e.Location.Curve
        low, top = c.GetEndPoint(0), c.GetEndPoint(1)       # rafters run heel -> top
        z_off = e.get_Parameter(DB.BuiltInParameter.Z_OFFSET_VALUE).AsDouble()
        seat, t = seat_point(roof_solids, top, low, z_off, half_v_raf)
        if seat is None:
            continue
        if seat.DistanceTo(top) < MIN_RAFTER:
            doc.Delete(e.Id)
            out['trimmed'].append([name, 'removed (shorter than %.1f ft)' % MIN_RAFTER])
            continue
        e.Location.Curve = DB.Line.CreateBound(seat, top)
        side = name.split('_')[1] if name.startswith(('COMMON_', 'OVER_')) else None
        out['trimmed'].append([name, round(low.DistanceTo(seat), 2)])
        if side in seats:
            r = roof_top(roof_solids, seat.X, seat.Y)
            seats[side].append(DB.XYZ(seat.X, seat.Y, r))
    doc.Regenerate()

    # 4. Sleepers (flat 2x8 valley boards) on the existing roof under each side's seats
    ssym = s3.framing_symbol(doc, *SLEEPER_TYPE)
    sset = dict(rafter_set)
    sset.update(symbol=ssym, z=1, z_off=SLEEPER_T / 2.0, y=rafter_set['y'], y_off=0.0)
    for side, pts in seats.items():
        if len(pts) < 2:
            continue
        pts.sort(key=lambda p: p.Y)
        # one piece between each pair of seats, so the sleeper follows the seat line
        for k, (a_, b_) in enumerate(zip(pts, pts[1:]), start=1):
            name = 'SLEEPER_%s_%d' % (side, k)
            fi = new_beam(doc, DB.Line.CreateBound(a_, b_), sset, name, phase)
            fi.get_Parameter(DB.BuiltInParameter.STRUCTURAL_BEND_DIR_ANGLE).Set(math.pi / 2.0)   # laid flat
            out['sleepers'].append({'name': name, 'from': [round(a_.X, 2), round(a_.Y, 2), round(a_.Z, 2)],
                                    'to': [round(b_.X, 2), round(b_.Y, 2), round(b_.Z, 2)],
                                    'length_ft': round(a_.DistanceTo(b_), 2)})
    doc.Regenerate()
    return out
