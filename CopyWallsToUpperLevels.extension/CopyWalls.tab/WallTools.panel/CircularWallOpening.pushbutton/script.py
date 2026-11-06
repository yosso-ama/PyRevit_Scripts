# -*- coding: utf-8 -*-
__title__ = "Circular\nOpening"
"""
Circular Opening in Wall
------------------------
SELECT THE WALL FIRST, then click this button.
Uses a face-based void family to cut a circular opening through the wall.
"""

import math
import os
import glob
import clr
import tempfile
from pyrevit import revit, DB, forms, script
from System.Collections.Generic import List

doc   = revit.doc
uidoc = revit.uidoc
app   = doc.Application

# ---------------------------------------------------------------------------
# HELPER
# ---------------------------------------------------------------------------
def prompt_float(title, prompt, default=""):
    val = forms.ask_for_string(prompt=prompt, title=title, default=default)
    if val is None:
        import sys; sys.exit()
    try:
        result = float(val.strip())
        if result <= 0:
            forms.alert("Value must be greater than zero.")
            import sys; sys.exit()
        return result
    except ValueError:
        forms.alert("Invalid number: '{}'".format(val))
        import sys; sys.exit()

# ---------------------------------------------------------------------------
# STEP 1 – Read pre-selection
# ---------------------------------------------------------------------------
selection_ids = uidoc.Selection.GetElementIds()

if not selection_ids or len(selection_ids) == 0:
    forms.alert(
        "No element selected.\n\n"
        "Please SELECT A WALL in the model first, then click this button again."
    )
    import sys; sys.exit()

if len(selection_ids) > 1:
    forms.alert("Multiple elements selected. Please select only one wall, then run again.")
    import sys; sys.exit()

element_id = list(selection_ids)[0]
wall = doc.GetElement(element_id)

if not isinstance(wall, DB.Wall):
    forms.alert(
        "Selected element is not a wall (type: {}).\n\n"
        "Please select a wall and run again.".format(type(wall))
    )
    import sys; sys.exit()

# ---------------------------------------------------------------------------
# STEP 2 – Locate family template
# ---------------------------------------------------------------------------
revit_ver = app.VersionNumber
search_roots = [
    r"C:\ProgramData\Autodesk\RVT {}\Family Templates".format(revit_ver),
    r"C:\ProgramData\Autodesk\RVT {}\Family Templates\English".format(revit_ver),
    r"C:\ProgramData\Autodesk\RVT {}\Family Templates\English_I".format(revit_ver),
    r"C:\ProgramData\Autodesk\RVT {}\Family Templates\English_US".format(revit_ver),
    r"C:\ProgramData\Autodesk\RVT {}\Family Templates\English-Imperial".format(revit_ver),
]

template_path = None
for root in search_roots:
    candidate = os.path.join(root, "Generic Model face based.rft")
    if os.path.exists(candidate):
        template_path = candidate
        break
    matches = glob.glob(os.path.join(root, "*face based*.rft"))
    if matches:
        template_path = matches[0]
        break

if template_path is None:
    for dirpath, dirnames, filenames in os.walk(r"C:\ProgramData\Autodesk"):
        for fname in filenames:
            if "face based" in fname.lower() and fname.endswith(".rft"):
                template_path = os.path.join(dirpath, fname)
                break
        if template_path:
            break

if template_path is None:
    forms.alert("Could not find 'Generic Model face based.rft'.\n"
                "Verify your Revit Family Templates folder.")
    import sys; sys.exit()

# ---------------------------------------------------------------------------
# STEP 3 – Get wall face geometry
# ---------------------------------------------------------------------------
opts = DB.Options()
opts.ComputeReferences = True
opts.IncludeNonVisibleObjects = False
opts.View = uidoc.ActiveView

best_face = None
best_area = 0.0
best_ref  = None

for geom_obj in wall.get_Geometry(opts):
    solid = None
    if isinstance(geom_obj, DB.Solid) and geom_obj.Volume > 1e-6:
        solid = geom_obj
    elif isinstance(geom_obj, DB.GeometryInstance):
        for g in geom_obj.GetInstanceGeometry():
            if isinstance(g, DB.Solid) and g.Volume > 1e-6:
                solid = g
                break
    if solid is None:
        continue
    for face in solid.Faces:
        if abs(face.FaceNormal.Z) < 0.1 and face.Area > best_area:
            best_area = face.Area
            best_face = face
            best_ref  = face.Reference

if best_face is None:
    forms.alert("Could not find a vertical face on the selected wall.")
    import sys; sys.exit()

face_normal = best_face.FaceNormal.Normalize()
wall_vec    = DB.XYZ(-face_normal.Y, face_normal.X, 0).Normalize()

# ---------------------------------------------------------------------------
# STEP 4 – Wall dimensions for validation
# ---------------------------------------------------------------------------
wall_curve = wall.Location
curve      = wall_curve.Curve
start_pt   = curve.GetEndPoint(0)
wall_len   = curve.Length

base_level  = doc.GetElement(
    wall.get_Parameter(DB.BuiltInParameter.WALL_BASE_CONSTRAINT).AsElementId())
wall_base_z = base_level.Elevation + \
    wall.get_Parameter(DB.BuiltInParameter.WALL_BASE_OFFSET).AsDouble()
wall_height = wall.get_Parameter(
    DB.BuiltInParameter.WALL_USER_HEIGHT_PARAM).AsDouble()

# ---------------------------------------------------------------------------
# STEP 5 – User inputs
# ---------------------------------------------------------------------------
horiz_in = prompt_float("Horizontal Offset",
    "Offset from wall START end to hole CENTER (inches):", "12")
elev_in  = prompt_float("Hole Elevation",
    "Height of hole CENTER above wall base (inches):", "48")
diam_in  = prompt_float("Hole Diameter",
    "Hole diameter (inches):", "6")

horiz_ft  = horiz_in / 12.0
elev_ft   = elev_in  / 12.0
radius_ft = (diam_in / 12.0) / 2.0

if horiz_ft > wall_len:
    forms.alert("Offset ({:.2f} ft) exceeds wall length ({:.2f} ft).".format(
        horiz_ft, wall_len))
    import sys; sys.exit()
if elev_ft - radius_ft < 0 or elev_ft + radius_ft > wall_height:
    forms.alert("Hole extends outside wall height ({:.2f} ft).".format(wall_height))
    import sys; sys.exit()

# Compute a candidate point at the correct position along the wall centerline
# then project it onto the actual face surface so it lands exactly on the face
candidate_pt = DB.XYZ(
    start_pt.X + wall_vec.X * horiz_ft,
    start_pt.Y + wall_vec.Y * horiz_ft,
    wall_base_z + elev_ft
)
proj_result = best_face.Project(candidate_pt)
if proj_result is not None:
    uv        = proj_result.UVPoint
    center_pt = best_face.Evaluate(uv)
else:
    center_pt = candidate_pt

# Read actual wall thickness to size the void correctly
wall_thickness_ft = wall.Width
extrusion_depth   = -(wall_thickness_ft + 2.0)  # 1 ft margin each side
thickness_in      = int(round(wall_thickness_ft * 12))
# ---------------------------------------------------------------------------
# STEP 6 – Build void family in memory
# ---------------------------------------------------------------------------
fam_doc    = app.NewFamilyDocument(template_path)
SEGMENTS   = 64
angle_step = 2.0 * math.pi / SEGMENTS

with DB.Transaction(fam_doc, "Create Void Extrusion") as t:
    t.Start()

    # Find the sketch plane in the face-based template
    sketch_plane = None
    for sp in (DB.FilteredElementCollector(fam_doc)
               .OfClass(DB.SketchPlane).ToElements()):
        try:
            if "ref" in sp.Name.lower() or "level" in sp.Name.lower():
                sketch_plane = sp
                break
        except Exception:
            pass
    if sketch_plane is None:
        all_sp = list(DB.FilteredElementCollector(fam_doc)
                      .OfClass(DB.SketchPlane).ToElements())
        sketch_plane = all_sp[0] if all_sp else \
            DB.SketchPlane.Create(fam_doc,
                DB.Plane.CreateByNormalAndOrigin(DB.XYZ.BasisZ, DB.XYZ.Origin))

    profile = DB.CurveArrArray()
    loop    = DB.CurveArray()
    pts = [DB.XYZ(radius_ft * math.cos(i * angle_step),
                  radius_ft * math.sin(i * angle_step), 0.0)
           for i in range(SEGMENTS)]
    for i in range(SEGMENTS):
        loop.Append(DB.Line.CreateBound(pts[i], pts[(i + 1) % SEGMENTS]))
    profile.Append(loop)

    # Negative depth = extrudes into the host face
    extrusion = fam_doc.FamilyCreate.NewExtrusion(False, profile, sketch_plane, extrusion_depth)
    extrusion.get_Parameter(DB.BuiltInParameter.ELEMENT_IS_CUTTING).Set(1)

    # Enable "Cut with Voids When Loaded" on the family
    # This is set via the family's OwnerFamily element, not the document
    owner_family = fam_doc.OwnerFamily
    if owner_family:
        fam_param = owner_family.get_Parameter(
            DB.BuiltInParameter.FAMILY_ALLOW_CUT_WITH_VOIDS)
        if fam_param and not fam_param.IsReadOnly:
            fam_param.Set(1)

    t.Commit()

tmp_path  = os.path.join(tempfile.gettempdir(),
    "CircularVoid_{:.4f}in_t{}in.rfa".format(diam_in, thickness_in).replace(".", "p"))
save_opts = DB.SaveAsOptions()
save_opts.OverwriteExistingFile = True
fam_doc.SaveAs(tmp_path, save_opts)
fam_doc.Close(False)

# ---------------------------------------------------------------------------
# STEP 7 – Load and place
# ---------------------------------------------------------------------------
# Load family — if already loaded, find the existing one by name
import os as _os
fam_name = _os.path.splitext(_os.path.basename(tmp_path))[0]

loaded_family = clr.Reference[DB.Family]()
with revit.Transaction("Load Void Family"):
    doc.LoadFamily(tmp_path, loaded_family)

family = loaded_family.Value

# If LoadFamily returned None, the family already exists — find it by name
if family is None:
    for f in (DB.FilteredElementCollector(doc)
              .OfClass(DB.Family).ToElements()):
        if f.Name == fam_name:
            family = f
            break

if family is None:
    forms.alert("Failed to load void family and could not find existing one.")
    import sys; sys.exit()

fam_symbol = None
for sym_id in family.GetFamilySymbolIds():
    fam_symbol = doc.GetElement(sym_id)
    break

if fam_symbol is None:
    forms.alert("No family symbol found in loaded family.")
    import sys; sys.exit()

with revit.Transaction("Place Void and Cut Wall"):
    if not fam_symbol.IsActive:
        fam_symbol.Activate()
        doc.Regenerate()

    instance = doc.Create.NewFamilyInstance(
        best_ref, center_pt, wall_vec, fam_symbol)

    if instance is None:
        forms.alert("Failed to place void family instance.")
        import sys; sys.exit()

    doc.Regenerate()

    # Match the phase of the void instance to the host wall
    # so it appears correctly in phased views
    host_phase_param = wall.get_Parameter(
        DB.BuiltInParameter.PHASE_CREATED)
    inst_phase_param = instance.get_Parameter(
        DB.BuiltInParameter.PHASE_CREATED)
    if host_phase_param and inst_phase_param and not inst_phase_param.IsReadOnly:
        inst_phase_param.Set(host_phase_param.AsElementId())

    DB.InstanceVoidCutUtils.AddInstanceVoidCut(doc, wall, instance)

    # Create a model line perpendicular to the wall through the hole center
    # The line runs along the face_normal direction (through the wall thickness)
    # extending radius_ft beyond each face for visibility
    line_length = wall_thickness_ft + radius_ft * 2 + 1.0
    line_start  = DB.XYZ(
        center_pt.X - face_normal.X * (wall_thickness_ft / 2.0 + radius_ft),
        center_pt.Y - face_normal.Y * (wall_thickness_ft / 2.0 + radius_ft),
        center_pt.Z
    )
    line_end = DB.XYZ(
        center_pt.X + face_normal.X * (wall_thickness_ft / 2.0 + radius_ft),
        center_pt.Y + face_normal.Y * (wall_thickness_ft / 2.0 + radius_ft),
        center_pt.Z
    )
    ref_line = DB.Line.CreateBound(line_start, line_end)

    # Find a sketch plane parallel to the XY plane at the hole center elevation
    # Model lines require a sketch plane
    plane      = DB.Plane.CreateByNormalAndOrigin(DB.XYZ.BasisZ, center_pt)
    skplane    = DB.SketchPlane.Create(doc, plane)
    model_line = doc.Create.NewModelCurve(ref_line, skplane)

    # Match phase of model line to the wall
    ml_phase = model_line.get_Parameter(DB.BuiltInParameter.PHASE_CREATED)
    if ml_phase and not ml_phase.IsReadOnly and host_phase_param:
        ml_phase.Set(host_phase_param.AsElementId())

forms.alert("Done. Circular opening cut into wall ({:.2f}\" diameter).".format(diam_in))

try:
    os.remove(tmp_path)
except Exception:
    pass
