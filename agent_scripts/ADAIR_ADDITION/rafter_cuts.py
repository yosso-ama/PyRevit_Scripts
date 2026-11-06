"""Rafter tails and plumb cuts for the PROPOSED sunroom roof.

Every rafter is lengthened past where it should end, then trimmed by void boxes
(a void-only Generic Model, cut with voids when loaded): at the ridge faces and
hip faces at the top, and at a fascia plane 18" out from the wall face at the
eave.  Hips get the same 18" tail, cut by both fascia planes at the corner.
"""
import math
from pyrevit.api import DB
from System import Int64

PHASE = 'Adair Addition'
OPTION = 'PROPOSED'
OVERHANG = 18.0 / 12
WALL_W, WALL_E, WALL_N = -57.787, -80.708, -19.479
TOP_EXT = 9.0 / 12               # past the centreline, so the top corner clears the face
TAIL_EXT = 26.0 / 12             # rafters: 18" horizontal at 10/12 is 23.4" along the slope
HIP_TAIL_EXT = 36.0 / 12         # hips: 29.6" along the slope for an 18" overhang
GM_RFT = r'C:\ProgramData\Autodesk\RVT 2026\Family Templates\English-Imperial\Generic Model.rft'
VOID_FAMILY = 'VOID - RAFTER CUT'
BOX_D, BOX_L, BOX_H = 4.0, 80.0, 30.0
CUT_Z = 1000.0
SQ2 = math.sqrt(0.5)


def eid(i):
    return DB.ElementId(Int64(i))


def comment(e):
    p = e.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    return (p.AsString() or '') if p else ''


def in_option(e):
    return e.DesignOption is not None and e.DesignOption.Name.startswith(OPTION)


def void_symbol(doc, app):
    """Void box: face on the family's YZ plane, box running +X (the side cut away).
    Built from the Generic Model template and loaded into the project (call with no
    open transaction in the project)."""
    for s in DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol).OfCategory(DB.BuiltInCategory.OST_GenericModel):
        if s.FamilyName == VOID_FAMILY:
            return s, False
    fam_doc = app.NewFamilyDocument(GM_RFT)
    try:
        t = DB.Transaction(fam_doc, 'void box')
        t.Start()
        fam_doc.OwnerFamily.get_Parameter(DB.BuiltInParameter.FAMILY_ALLOW_CUT_WITH_VOIDS).Set(1)
        z0 = -BOX_H / 2.0
        pts = [DB.XYZ(0, -BOX_L / 2, z0), DB.XYZ(BOX_D, -BOX_L / 2, z0),
               DB.XYZ(BOX_D, BOX_L / 2, z0), DB.XYZ(0, BOX_L / 2, z0)]
        loop = DB.CurveArray()
        for p, q in zip(pts, pts[1:] + pts[:1]):
            loop.Append(DB.Line.CreateBound(p, q))
        prof = DB.CurveArrArray()
        prof.Append(loop)
        sp = DB.SketchPlane.Create(fam_doc, DB.Plane.CreateByNormalAndOrigin(DB.XYZ.BasisZ, DB.XYZ(0, 0, z0)))
        fam_doc.FamilyCreate.NewExtrusion(False, prof, sp, BOX_H)
        t.Commit()
        fam = fam_doc.LoadFamily(doc)
    finally:
        fam_doc.Close(False)
    t = DB.Transaction(doc, 'name void family')
    t.Start()
    fam.Name = VOID_FAMILY
    s = doc.GetElement(list(fam.GetFamilySymbolIds())[0])
    s.Name = 'BOX'
    t.Commit()
    return s, True


def place_void(doc, sym, face_pt, d, name, phase, z=CUT_Z):
    """Void instance whose face passes through face_pt, cutting away the side d points to."""
    p = DB.XYZ(face_pt.X, face_pt.Y, z)
    inst = doc.Create.NewFamilyInstance(p, sym, DB.Structure.StructuralType.NonStructural)
    ang = math.atan2(d.Y, d.X)
    if abs(ang) > 1e-9:
        DB.ElementTransformUtils.RotateElement(doc, inst.Id, DB.Line.CreateBound(p, p + DB.XYZ.BasisZ), ang)
    inst.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).Set(name)
    inst.get_Parameter(DB.BuiltInParameter.PHASE_CREATED).Set(phase.Id)
    return inst


def plan_xy(p):
    return DB.XYZ(p.X, p.Y, 0)


def face(member, half, ref_pt):
    """(face point, cut direction) for the face of a ridge/hip on ref_pt's side."""
    c = member.Location.Curve
    a, b = plan_xy(c.GetEndPoint(0)), plan_xy(c.GetEndPoint(1))
    u = (b - a).Normalize()
    n = DB.XYZ(-u.Y, u.X, 0)
    side = 1.0 if (plan_xy(ref_pt) - a).DotProduct(n) > 0 else -1.0
    return a + n * (half * side), n * (-side)


def run(doc, app_sym):
    sym = app_sym
    if not sym.IsActive:
        sym.Activate()
    phase = [p for p in doc.Phases if p.Name == PHASE][0]
    framing = dict((comment(e), e) for e in DB.FilteredElementCollector(doc)
                   .OfCategory(DB.BuiltInCategory.OST_StructuralFraming).WhereElementIsNotElementType()
                   if in_option(e))
    ridge, hip_w, hip_e = framing['RIDGE'], framing['HIP_W'], framing['HIP_E']
    rb = ridge.get_BoundingBox(None)
    half = (rb.Max.X - rb.Min.X) / 2.0
    cx = ridge.Location.Curve.GetEndPoint(0).X

    faces = {}

    def void_for(key, pt, d):
        if key not in faces:
            faces[key] = place_void(doc, sym, pt, d, 'RAFTER CUT - ' + key, phase)
        return faces[key]

    mid_x, mid_y = cx, WALL_N + 15.0
    fascia = {'W': (DB.XYZ(WALL_W + OVERHANG, mid_y, 0), DB.XYZ(1, 0, 0)),
              'E': (DB.XYZ(WALL_E - OVERHANG, mid_y, 0), DB.XYZ(-1, 0, 0)),
              'N': (DB.XYZ(mid_x, WALL_N - OVERHANG, 0), DB.XYZ(0, -1, 0))}
    out = {'tails': [], 'tops': [], 'cuts': [], 'skipped': []}
    work = []
    for name in sorted(framing):
        e = framing[name]
        kind = name.split('_')[0]
        if kind not in ('COMMON', 'JACK', 'KING', 'OVER', 'HIP'):
            continue
        c = e.Location.Curve
        s, t = c.GetEndPoint(0), c.GetEndPoint(1)
        cuts = []
        wall = None
        if abs(s.X - WALL_W) < 0.01:
            wall = ['W']
        elif abs(s.X - WALL_E) < 0.01:
            wall = ['E']
        elif abs(s.Y - WALL_N) < 0.01:
            wall = ['N']
        if kind == 'HIP':
            wall = ['W', 'N'] if name == 'HIP_W' else ['E', 'N']
        if wall:
            for w in wall:
                cuts.append(('FASCIA ' + w, fascia[w]))
        if kind in ('COMMON', 'OVER'):
            side = 'W' if s.X > cx else 'E'
            cuts.append(('RIDGE ' + side, face(ridge, half, s)))
        elif kind in ('JACK', 'KING'):
            if kind == 'KING':
                hips = [hip_w, hip_e]
            elif name.startswith('JACK_W') or (name.startswith('JACK_N') and s.X > cx):
                hips = [hip_w]
            else:
                hips = [hip_e]
            for h in hips:
                pt, d = face(h, half, s)
                tag = comment(h).replace('_', ' ')
                cuts.append(('%s %s' % (tag, 'A' if d.DotProduct(DB.XYZ(1, 1, 0)) > 0 else 'B'), (pt, d)))
        work.append((name, e, kind, bool(wall), cuts))

    for name, e, kind, tail, cuts in work:
        if tail:
            e.get_Parameter(DB.BuiltInParameter.START_EXTENSION).Set(HIP_TAIL_EXT if kind == 'HIP' else TAIL_EXT)
            out['tails'].append(name)
        if kind != 'HIP':
            e.get_Parameter(DB.BuiltInParameter.END_EXTENSION).Set(TOP_EXT)
            out['tops'].append(name)
    doc.Regenerate()
    for name, e, kind, tail, cuts in work:
        for key, (pt, d) in cuts:
            v = void_for(key, pt, d)
            try:
                DB.InstanceVoidCutUtils.AddInstanceVoidCut(doc, e, v)
                out['cuts'].append([name, key])
            except Exception as ex:
                out['skipped'].append([name, key, str(ex)[:120]])
    doc.Regenerate()
    out['voids'] = dict((k, [v.Id.Value, v.DesignOption.Name if v.DesignOption else 'Main Model']) for k, v in faces.items())
    return out


def solid_points(e):
    out = []
    for g in e.get_Geometry(DB.Options()):
        sols = [g] if isinstance(g, DB.Solid) else (list(g.GetInstanceGeometry()) if isinstance(g, DB.GeometryInstance) else [])
        for s in sols:
            if isinstance(s, DB.Solid) and s.Volume > 0:
                for ed in s.Edges:
                    c = ed.AsCurve()
                    out += [c.GetEndPoint(0), c.GetEndPoint(1)]
    return out


def add_soffit(doc, sym):
    """Level soffit cut on the hip tails at the bottom of the rafter tails' plumb
    cut: one void box lying under the north eave, its top face at that elevation,
    running 4 ft out from just inside the north wall and across both hips."""
    phase = [p for p in doc.Phases if p.Name == PHASE][0]
    framing = dict((comment(e), e) for e in DB.FilteredElementCollector(doc)
                   .OfCategory(DB.BuiltInCategory.OST_StructuralFraming).WhereElementIsNotElementType()
                   if in_option(e))
    tails = [e for n, e in framing.items() if n.startswith(('COMMON_', 'JACK_', 'KING_'))
             and e.get_Parameter(DB.BuiltInParameter.START_EXTENSION).AsDouble() > 0]
    soffit_z = min(min(q.Z for q in solid_points(e)) for e in tails)
    cx = framing['RIDGE'].Location.Curve.GetEndPoint(0).X
    face_pt = DB.XYZ(cx, WALL_N + 0.5, 0)
    v = place_void(doc, sym, face_pt, DB.XYZ(0, -1, 0), 'RAFTER CUT - SOFFIT HIPS', phase, soffit_z - BOX_H / 2.0)
    for n in ('HIP_W', 'HIP_E'):
        DB.InstanceVoidCutUtils.AddInstanceVoidCut(doc, framing[n], v)
    doc.Regenerate()
    return soffit_z, v
