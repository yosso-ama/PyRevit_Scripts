"""Update the sunroom hip-roof framing in PROPOSED LAYOUT to the structural-
ridge scheme of roof_framing_model.py: no rafter ties, (2)2x12 ridge, and 4x6
posts from the ceiling joists up to the ridge and hips.

Script coords (roof_framing_model.py): X = east, Y = up, Z = south, origin =
NW plate corner.  Model: x = X0 - X, y = Y0 + Z, z = plate + Y (as placed).
"""
import math
from pyrevit.api import DB

X0, Y0 = -58.0832, -19.8133
WIDTH, LENGTH = 22.625, 25.313
PITCH = 10.0 / 12.0
RUN = WIDTH / 2.0
H_RIDGE = RUN * PITCH
BATH_WALL_Y = 19.0 + 5.75 / 12.0
OPTION = 'PROPOSED LAYOUT'
PHASE = 'Adair Addition'
POST_TYPE = '4x6'
POST_B, POST_D = 3.5 / 12, 5.5 / 12        # b along the column's local x, d along its local y
RIDGE_TYPE = '(2)2x12'
JOIST_D = 9.25 / 12                        # 2x10 ceiling joists, centered on the plate line
BEAM_D = 11.25 / 12                        # ridge and hips, centered on their lines
HIP_SLOPE = PITCH / math.sqrt(2.0)


def to_model(X, Z):
    return X0 - X, Y0 + Z


# (label, script X, script Z, script Y of the beam line, member it carries,
#  long-side direction in plan as a model-space angle)
POSTS = [
    ('POST - APEX', RUN, RUN, H_RIDGE, 'ridge', math.radians(90)),
    ('POST - RIDGE @ BATH WALL', RUN, BATH_WALL_Y, H_RIDGE, 'ridge', math.radians(90)),
    ('POST - HIP W MID', RUN / 2.0, RUN / 2.0, H_RIDGE / 2.0, 'hip', math.radians(135)),
    ('POST - HIP E MID', WIDTH - RUN / 2.0, RUN / 2.0, H_RIDGE / 2.0, 'hip', math.radians(45)),
]


def type_name(e):
    return e.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString()


def in_option(e, opt_name):
    return e.DesignOption is not None and e.DesignOption.Name.startswith(opt_name)


def framing(doc, prefix):
    out = []
    for e in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_StructuralFraming) \
            .WhereElementIsNotElementType():
        c = e.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).AsString() or ''
        if c.startswith(prefix) and in_option(e, OPTION):
            out.append(e)
    return out


def post_symbol(doc):
    syms = [s for s in DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol)
            .OfCategory(DB.BuiltInCategory.OST_StructuralColumns) if s.FamilyName == 'Timber-Column']
    for s in syms:
        if type_name(s) == POST_TYPE:
            return s, False, None
    base = [s for s in syms if type_name(s) == '8x8'][0]
    s = base.Duplicate(POST_TYPE)
    dims = {}
    for p in s.Parameters:
        if p.StorageType == DB.StorageType.Double and not p.IsReadOnly:
            dims[p.Definition.Name] = p
    set_ = []
    for name, val in (('b', POST_B), ('d', POST_D), ('h', POST_D), ('Width', POST_B), ('Depth', POST_D)):
        if name in dims:
            dims[name].Set(val)
            set_.append(name)
    return s, True, {'params_set': set_, 'double_params': sorted(dims)}


RIDGE_JOIST = 'CJ_%.2f' % RUN              # ceiling joist on the ridge line, under the ridge posts
JOIST_TEMPLATE = 'CJ_11.96'                # nearest existing joist; copied across to the ridge line


def add_ridge_joist(doc):
    """Copy the nearest ceiling joist onto the ridge line (x = RUN) unless one is there."""
    joists = framing(doc, 'CJ_')
    xr = to_model(RUN, 0.0)[0]
    for j in joists:
        if abs(j.Location.Curve.GetEndPoint(0).X - xr) < 0.05:
            return {'status': 'already present', 'id': j.Id.Value}
    src = [j for j in joists
           if j.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).AsString() == JOIST_TEMPLATE][0]
    dx = xr - src.Location.Curve.GetEndPoint(0).X
    new_id = list(DB.ElementTransformUtils.CopyElement(doc, src.Id, DB.XYZ(dx, 0.0, 0.0)))[0]
    j = doc.GetElement(new_id)
    j.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).Set(RIDGE_JOIST)
    c = j.Location.Curve
    a, b = c.GetEndPoint(0), c.GetEndPoint(1)
    return {'status': 'added', 'id': new_id.Value, 'name': RIDGE_JOIST, 'type': j.Name,
            'copied_from': [src.Id.Value, JOIST_TEMPLATE], 'shift_ft': round(dx, 4),
            'design_option': j.DesignOption.Name if j.DesignOption else 'Main Model',
            'phase': doc.GetElement(j.CreatedPhaseId).Name,
            'line': [[round(a.X, 3), round(a.Y, 3), round(a.Z, 3)], [round(b.X, 3), round(b.Y, 3), round(b.Z, 3)]]}


def run(doc):
    level = [l for l in DB.FilteredElementCollector(doc).OfClass(DB.Level) if l.Name == 'TOP OF WALLS'][0]
    plate = level.ProjectElevation
    phase = [p for p in doc.Phases if p.Name == PHASE][0]
    out = {}

    ties = framing(doc, 'TIE_')
    out['ties_deleted'] = len(ties)
    for e in ties:
        doc.Delete(e.Id)

    ridges = framing(doc, 'RIDGE')
    rtype = [s for s in DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol)
             .OfCategory(DB.BuiltInCategory.OST_StructuralFraming)
             if s.FamilyName == 'Dimension Lumber' and type_name(s) == RIDGE_TYPE][0]
    out['ridge'] = []
    for r in ridges:
        before = r.Name
        r.ChangeTypeId(rtype.Id)
        out['ridge'].append([r.Id.Value, before, RIDGE_TYPE])

    out['ridge_joist'] = add_ridge_joist(doc)

    sym, new_type, info = post_symbol(doc)
    if not sym.IsActive:
        sym.Activate()
    doc.Regenerate()
    out['post_type'] = [sym.Id.Value, POST_TYPE, 'new' if new_type else 'existing', info]

    bottom = plate + JOIST_D / 2.0                 # top of the ceiling joists
    out['posts'] = []
    for label, X, Z, Yb, kind, ang in POSTS:
        x, y = to_model(X, Z)
        z_line = plate + Yb
        half = BEAM_D / 2.0 if kind == 'ridge' else BEAM_D / 2.0 * math.sqrt(1.0 + HIP_SLOPE ** 2)
        top = z_line - half                        # underside of the ridge / hip
        col = doc.Create.NewFamilyInstance(DB.XYZ(x, y, plate), sym, level, DB.Structure.StructuralType.Column)
        col.get_Parameter(DB.BuiltInParameter.FAMILY_BASE_LEVEL_PARAM).Set(level.Id)
        col.get_Parameter(DB.BuiltInParameter.FAMILY_TOP_LEVEL_PARAM).Set(level.Id)
        col.get_Parameter(DB.BuiltInParameter.FAMILY_BASE_LEVEL_OFFSET_PARAM).Set(bottom - plate)
        col.get_Parameter(DB.BuiltInParameter.FAMILY_TOP_LEVEL_OFFSET_PARAM).Set(top - plate)
        col.get_Parameter(DB.BuiltInParameter.PHASE_CREATED).Set(phase.Id)
        col.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).Set(label)
        rot = ang - math.radians(90)               # family d (long side) runs along model y
        if abs(rot) > 1e-6:
            axis = DB.Line.CreateBound(DB.XYZ(x, y, plate), DB.XYZ(x, y, plate + 1.0))
            DB.ElementTransformUtils.RotateElement(doc, col.Id, axis, rot)
        out['posts'].append({'label': label, 'id': col.Id.Value, 'xy': [round(x, 3), round(y, 3)],
                             'bottom': round(bottom, 3), 'top': round(top, 3),
                             'height_in': round((top - bottom) * 12, 2), 'rot_deg': round(math.degrees(rot), 1)})
    doc.Regenerate()

    # Ceiling joists under each post (a post between joists needs blocking or a header)
    joists = framing(doc, 'CJ_')
    for p in out['posts']:
        x, y = p['xy']
        best = None
        for j in joists:
            c = j.Location.Curve
            a, b = c.GetEndPoint(0), c.GetEndPoint(1)
            if min(a.Y, b.Y) - 0.1 <= y <= max(a.Y, b.Y) + 0.1:
                dx = abs(a.X - x)
                if best is None or dx < best[0]:
                    best = (dx, j.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).AsString())
        p['nearest_joist'] = None if best is None else [best[1], round(best[0] * 12, 1)]
    out['framing_left'] = dict((k, len(framing(doc, k))) for k in ('RIDGE', 'HIP_', 'JACK_', 'KING_', 'COMMON_', 'TIE_', 'CJ_'))
    return out
