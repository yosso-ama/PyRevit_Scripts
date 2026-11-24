# -*- coding: utf-8 -*-
"""Center of Rigidity, Center of Mass & Eccentricity from detail lines.

Workflow
--------
1. Select the detail lines that trace the plan extents of your masonry walls
   (each line = one wall/pier), OR just run and pick them when prompted.
2. If MASS_MODE needs the diaphragm, you are then prompted to pick a CLOSED
   loop of detail lines outlining the floor plate; its area centroid is the
   center of mass.
3. The script writes a CSV (per-wall table + summary) and prints a report:
   center of rigidity, center of mass, and the eccentricity between them.

Engineering basis
-----------------
Rigidity of each solid wall/pier (masonry relative-rigidity method, G=0.4*Em):
    cantilever (fixed-free):   R = t / ( 4*(h/L)^3 + 3*(h/L) )
    fixed-fixed:               R = t / (   (h/L)^3 + 3*(h/L) )
resolved onto global axes by orientation theta:
    Rx = R*cos(theta)^2 ,  Ry = R*sin(theta)^2
    X_cr = SUM(Ry*x)/SUM(Ry) ,  Y_cr = SUM(Rx*y)/SUM(Rx)
    J    = SUM[ Rx*(y-Y_cr)^2 + Ry*(x-X_cr)^2 ]   (torsional rigidity)

Center of mass (MASS_MODE):
    "diaphragm" : area centroid of the diaphragm outline (uniform mass/area).
    "walls"     : mass-weighted centroid of the walls, m_i = w_wall * L_i * h.
    "combined"  : diaphragm mass (floor psf * area) + wall self-mass, combined.

Eccentricity:  ex = X_com - X_cr ,  ey = Y_com - Y_cr ,  e = hypot(ex, ey).
Accidental eccentricity (ASCE 7 12.8.4.2), from the plan bounding box (Lx,Ly):
    for X-direction force:  e_acc = 0.05 * Ly
    for Y-direction force:  e_acc = 0.05 * Lx

Assumptions / limitations
-------------------------
* One uniform height/thickness for all walls (edit CONFIG, or read from a
  shared parameter per line). Solid walls, no openings.
* Diaphragm assumed a single closed simple polygon of straight detail lines.
* Non-orthogonal walls: axis-coupling term ignored (common simplification).
* Coordinates are Revit project/model coordinates (feet internally).
"""

import math
import csv
import os

from pyrevit import revit, DB, UI, forms, script
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException

# ------------------------------------------------------------------ CONFIG ---
BOUNDARY          = "cantilever"  # "cantilever" (fixed-free) or "fixed" (fixed-fixed)
WALL_HEIGHT_FT    = 17.33          # wall/story height, feet
WALL_THICK_IN     = 11.625         # wall thickness, inches (7.625 = nominal 8" CMU)

MASS_MODE         = "diaphragm"   # "diaphragm" | "walls" | "combined"
FLOOR_PRESSURE_PSF = 75.0         # diaphragm weight, psf   (combined mode)
WALL_WEIGHT_PSF    = 56.0         # wall face weight, psf   (walls/combined modes)

OUTPUT_UNITS      = "ft"          # report coordinate units: "ft","in","m","mm"
PROMPT_FOR_INPUTS = True          # pop dialogs for height/thickness at run time
CHAIN_TOL_FT      = 0.02          # endpoint match tolerance when closing the loop
SHIFT_TO_EXTENTS  = True          # fallback origin at bottom-left of extents when
                                  # no origin is picked (see PICK_COORD_SYSTEM)
PICK_COORD_SYSTEM = True          # ask user to pick an origin point and a +X-axis
                                  # direction; the analysis runs in that frame
WALLS_CSV         = "cor_walls.csv"    # per-wall table (tidy, one header row)
SUMMARY_CSV       = "cor_summary.csv"  # summary as Parameter,Value rows
# fixed names -> Power Query points at stable paths; Data > Refresh All re-reads
# -----------------------------------------------------------------------------

_FT_TO = {"ft": 1.0, "in": 12.0, "m": 0.3048, "mm": 304.8}

doc    = revit.doc
uidoc  = revit.uidoc
output = script.get_output()


class _DetailLineFilter(ISelectionFilter):
    def AllowElement(self, element):
        return isinstance(element, DB.DetailLine)

    def AllowReference(self, reference, position):
        return False



def get_shear_wall_line_style_name():
    """The dedicated line style used for shear wall detail lines."""
    return "SHEAR WALL"


def collect_shear_wall_detail_lines(doc, view):
    """
    Auto-collect detail lines drawn with the 'SHEAR WALL' line style
    in the given (plan) view. No user picking required.

    Returns a list of DB.DetailLine.
    """
    target_name = get_shear_wall_line_style_name()

    collector = (DB.FilteredElementCollector(doc, view.Id)
                 .OfClass(DB.CurveElement)
                 .WhereElementIsNotElementType())

    shear_lines = []
    for el in collector:
        # Only detail lines (not model lines, symbolic lines, etc.)
        if not isinstance(el, DB.DetailLine):
            continue

        gstyle = el.LineStyle          # returns a GraphicsStyle
        if gstyle is None:
            continue

        if gstyle.Name == target_name:
            shear_lines.append(el)

    return shear_lines


def confirm_shear_wall_selection(count):
    """Validation window: show the auto-collected count and require the user to
    confirm before the calculation runs. Returns True to proceed, False to abort.
    """
    return forms.alert(
        "Found {} shear wall segment(s) on the '{}' line style in this view.\n\n"
        "Proceed with the center-of-rigidity calculation?"
        .format(count, get_shear_wall_line_style_name()),
        title="Center of Rigidity",
        yes=True, no=True)


def pick_detail_lines(prompt, use_preselection=False):
    """Return a list of DetailLine elements from selection or interactive pick."""
    if use_preselection:
        pre = [doc.GetElement(eid) for eid in uidoc.Selection.GetElementIds()]
        pre = [e for e in pre if isinstance(e, DB.DetailLine)]
        if pre:
            return pre
    try:
        refs = uidoc.Selection.PickObjects(
            ObjectType.Element, _DetailLineFilter(), prompt)
    except OperationCanceledException:
        return []
    return [doc.GetElement(r) for r in refs]


def eid_value(element_id):
    """Element id as an int, across Revit versions.

    Revit 2024 deprecated ElementId.IntegerValue and 2025+ removed it in favor
    of ElementId.Value (a 64-bit long). Prefer Value, fall back to IntegerValue.
    """
    try:
        return element_id.Value
    except AttributeError:
        return element_id.IntegerValue


def line_segments(dlines):
    """Return [((x1,y1),(x2,y2),id), ...] and count of skipped non-straight lines."""
    segs, skipped = [], 0
    for dl in dlines:
        crv = dl.GeometryCurve
        if not isinstance(crv, DB.Line):
            skipped += 1
            continue
        p0, p1 = crv.GetEndPoint(0), crv.GetEndPoint(1)
        segs.append(((p0.X, p0.Y), (p1.X, p1.Y), eid_value(dl.Id)))
    return segs, skipped


def wall_props(x1, y1, x2, y2, height_ft, thick_ft, boundary):
    dx, dy = x2 - x1, y2 - y1
    L = math.hypot(dx, dy)
    if L < 1e-9:
        return None
    theta = math.atan2(dy, dx)
    hL = height_ft / L
    bracket = (4.0 * hL ** 3 + 3.0 * hL) if boundary == "cantilever" \
        else (hL ** 3 + 3.0 * hL)
    R = thick_ft / bracket
    return {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "L": L, "theta": theta,
            "cx": (x1 + x2) / 2.0, "cy": (y1 + y2) / 2.0,
            "R": R, "Rx": R * math.cos(theta) ** 2, "Ry": R * math.sin(theta) ** 2}


def chain_segments(segs, tol):
    """Chain unordered (p0,p1) segments into an ordered loop of vertices."""
    if not segs:
        return [], False, 0
    remaining = [[s[0], s[1]] for s in segs]
    loop = list(remaining.pop(0))
    close = lambda a, b: abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol
    progress = True
    while remaining and progress:
        progress = False
        end = loop[-1]
        for i, (a, b) in enumerate(remaining):
            if close(a, end):
                loop.append(b); remaining.pop(i); progress = True; break
            if close(b, end):
                loop.append(a); remaining.pop(i); progress = True; break
    closed = close(loop[0], loop[-1])
    if closed:
        loop = loop[:-1]
    return loop, closed, len(remaining)


def poly_area_centroid(pts):
    """Shoelace area (abs) and centroid for an ordered vertex list."""
    n = len(pts)
    A2 = cx = cy = 0.0
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        cr = x0 * y1 - x1 * y0
        A2 += cr; cx += (x0 + x1) * cr; cy += (y0 + y1) * cr
    A = A2 / 2.0
    if abs(A) < 1e-12:
        return 0.0, sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n
    return abs(A), cx / (6.0 * A), cy / (6.0 * A)


def bbox(points):
    xs = [p[0] for p in points]; ys = [p[1] for p in points]
    return max(xs) - min(xs), max(ys) - min(ys)


def pick_point(prompt):
    """Pick a single point in the active view; None if the user presses Esc."""
    try:
        return uidoc.Selection.PickPoint(prompt)
    except OperationCanceledException:
        return None


def make_transform(origin_xy, theta):
    """Return a fn mapping project (x,y) into a frame with the given origin and
    +X direction (theta = angle of the chosen x-axis from global X, radians).
    Rigid transform: translate to origin, then rotate by -theta."""
    ox, oy = origin_xy
    c, s = math.cos(theta), math.sin(theta)

    def tf(x, y):
        vx, vy = x - ox, y - oy
        return (vx * c + vy * s, -vx * s + vy * c)
    return tf


def get_export_folder():
    """Ask for the export folder, defaulting to the last one used.

    The choice is stored in this script's pyRevit config so it pre-fills on the
    next run. If the picker is cancelled, fall back to the stored folder.
    """
    cfg = script.get_config()
    try:
        stored = cfg.get_option("export_folder", None)
    except Exception:
        stored = None   # key absent on first run; some pyRevit builds raise
    picked = forms.pick_folder(title="Choose the export folder for the CSV files")
    folder = picked or stored
    if folder and os.path.isdir(folder):
        try:
            cfg.export_folder = folder
            script.save_config()
        except Exception:
            pass        # persistence is best-effort; proceed regardless
        return folder
    return None


def main():
    global WALL_HEIGHT_FT, WALL_THICK_IN

    # ---- export folder (asked once, remembered for next time) --------------
    folder = get_export_folder()
    if not folder:
        forms.alert("No export folder chosen.", title="Center of Rigidity")
        return

    # ---- walls (auto-collected by the 'SHEAR WALL' line style) --------------
    view = doc.ActiveView
    if not isinstance(view, DB.ViewPlan):
        forms.alert("Run this from a plan view that contains the shear wall "
                    "detail lines.", title="Center of Rigidity")
        return

    wall_lines = collect_shear_wall_detail_lines(doc, view)
    if not wall_lines:
        forms.alert(
            "No detail lines found with the '%s' line style in this view.\n\n"
            "Check that the walls use that line style and that you are in the "
            "correct plan view." % get_shear_wall_line_style_name(),
            title="Center of Rigidity")
        return

    # validation window: show the count, let the user cancel before we compute
    if not confirm_shear_wall_selection(len(wall_lines)):
        return

    if PROMPT_FOR_INPUTS:
        h = forms.ask_for_string(default=str(WALL_HEIGHT_FT),
                                 prompt="Wall height (feet):",
                                 title="Center of Rigidity")
        t = forms.ask_for_string(default=str(WALL_THICK_IN),
                                 prompt="Wall thickness (inches):",
                                 title="Center of Rigidity")
        if h:
            WALL_HEIGHT_FT = float(h)
        if t:
            WALL_THICK_IN = float(t)
    thick_ft = WALL_THICK_IN / 12.0

    # ---- gather raw geometry (project coordinates) -------------------------
    wsegs, wskip = line_segments(wall_lines)

    # diaphragm loop, picked before the coordinate system so it can inform the
    # fallback extents and share the same transform.
    dia_note = ""
    mode = MASS_MODE
    gloop = None            # diaphragm loop vertices in project coordinates
    if mode in ("diaphragm", "combined"):
        dlines = pick_detail_lines(
            "Select the CLOSED loop of detail lines outlining the slab / "
            "diaphragm, then Finish.  (Cancel to fall back to wall-only mass.)")
        dsegs, _ = line_segments(dlines)
        if dsegs:
            gloop, closed, leftover = chain_segments(
                [(s[0], s[1]) for s in dsegs], CHAIN_TOL_FT)
            if not closed:
                dia_note = ("diaphragm loop did not close (tol %.3f ft); "
                            "centroid approximate" % CHAIN_TOL_FT)
            elif leftover:
                dia_note = "%d diaphragm line(s) not part of the loop" % leftover
        else:
            dia_note = "no diaphragm loop picked; used wall-only mass"
            mode = "walls"

    # ---- coordinate system: origin + x-axis --------------------------------
    # Pick an origin point and a point on the +X axis. All geometry is then
    # transformed into that frame, so the Rx/Ry split, COR, COM and eccentricity
    # components all align with the chosen axes. Esc either pick to fall back.
    origin_g = None
    theta = 0.0
    picked_cs = False
    if PICK_COORD_SYSTEM:
        p0 = pick_point("Pick the ORIGIN point   (Esc = use extents corner).")
        if p0 is not None:
            origin_g = (p0.X, p0.Y)
            picked_cs = True
            p1 = pick_point("Pick a point on the +X axis   (Esc = keep global X).")
            if p1 is not None:
                theta = math.atan2(p1.Y - p0.Y, p1.X - p0.X)

    # global extents (for the fallback origin)
    g_pts = [s[0] for s in wsegs] + [s[1] for s in wsegs]
    if gloop:
        g_pts += gloop
    gminx = min(p[0] for p in g_pts)
    gminy = min(p[1] for p in g_pts)
    if origin_g is None:
        origin_g = (gminx, gminy) if SHIFT_TO_EXTENTS else (0.0, 0.0)
        theta = 0.0
    tf = make_transform(origin_g, theta)
    xaxis_deg = math.degrees(theta)
    if picked_cs and theta:
        frame_desc = "picked origin + x-axis"
    elif picked_cs:
        frame_desc = "picked origin, global X"
    elif SHIFT_TO_EXTENTS:
        frame_desc = "extents corner, global X"
    else:
        frame_desc = "project origin, global X"

    # ---- build walls in the LOCAL frame ------------------------------------
    walls = []
    for a, b, eid in wsegs:
        (lx1, ly1), (lx2, ly2) = tf(a[0], a[1]), tf(b[0], b[1])
        w = wall_props(lx1, ly1, lx2, ly2, WALL_HEIGHT_FT, thick_ft, BOUNDARY)
        if w:
            w["id"] = eid
            walls.append(w)
    if not walls:
        forms.alert("Selected lines produced no valid straight walls.",
                    title="Center of Rigidity")
        return

    # ---- diaphragm centroid in the LOCAL frame -----------------------------
    dia_area = None
    dia_c = None
    lloop = None
    if gloop:
        lloop = [tf(x, y) for (x, y) in gloop]
        dia_area, dcx, dcy = poly_area_centroid(lloop)
        dia_c = (dcx, dcy)

    # ---- center of rigidity ------------------------------------------------
    sRx = sum(w["Rx"] for w in walls)
    sRy = sum(w["Ry"] for w in walls)
    Xcr = sum(w["Ry"] * w["cx"] for w in walls) / sRy if sRy else 0.0
    Ycr = sum(w["Rx"] * w["cy"] for w in walls) / sRx if sRx else 0.0
    J = sum(w["Rx"] * (w["cy"] - Ycr) ** 2 + w["Ry"] * (w["cx"] - Xcr) ** 2
            for w in walls)

    # ---- wall self-mass -----------------------------------------------------
    for w in walls:
        w["m"] = WALL_WEIGHT_PSF * w["L"] * WALL_HEIGHT_FT
    Mw = sum(w["m"] for w in walls)

    # ---- center of mass -----------------------------------------------------
    if mode == "diaphragm":
        Xcom, Ycom = dia_c
    elif mode == "walls":
        Xcom = sum(w["m"] * w["cx"] for w in walls) / Mw if Mw else Xcr
        Ycom = sum(w["m"] * w["cy"] for w in walls) / Mw if Mw else Ycr
    else:  # combined
        Mdia = FLOOR_PRESSURE_PSF * dia_area
        Mtot = Mdia + Mw
        Xcom = (Mdia * dia_c[0] + sum(w["m"] * w["cx"] for w in walls)) / Mtot
        Ycom = (Mdia * dia_c[1] + sum(w["m"] * w["cy"] for w in walls)) / Mtot

    # ---- eccentricity -------------------------------------------------------
    ex = Xcom - Xcr
    ey = Ycom - Ycr
    e = math.hypot(ex, ey)

    # ---- plan dimensions in the LOCAL frame (for accidental eccentricity) --
    lpts = [(w["x1"], w["y1"]) for w in walls] + \
           [(w["x2"], w["y2"]) for w in walls]
    if lloop:
        lpts += lloop
    minx = min(p[0] for p in lpts)
    miny = min(p[1] for p in lpts)
    maxx = max(p[0] for p in lpts)
    maxy = max(p[1] for p in lpts)
    Lx, Ly = maxx - minx, maxy - miny
    ox, oy = 0.0, 0.0        # coordinates are already in the local frame
    eacc_x = 0.05 * Ly   # for force applied in X
    eacc_y = 0.05 * Lx   # for force applied in Y

    # ---- write two tidy CSVs -----------------------------------------------
    u = _FT_TO[OUTPUT_UNITS]
    un = OUTPUT_UNITS
    walls_path = os.path.join(folder, WALLS_CSV)
    summary_path = os.path.join(folder, SUMMARY_CSV)

    # per-wall table: one header row, numeric rows, unit-free column names so
    # the Power Query "Changed Type" step stays valid if OUTPUT_UNITS changes.
    with open(walls_path, "wb") as f:
        wr = csv.writer(f)
        wr.writerow(["Line Id", "X1", "Y1", "X2", "Y2", "Length", "Angle",
                     "Centroid X", "Centroid Y", "h/L", "R", "Rx", "Ry",
                     "Wall wt"])
        for w in walls:
            ang = math.degrees(w["theta"]) % 180.0
            wr.writerow([w["id"],
                         round((w["x1"] - ox) * u, 4), round((w["y1"] - oy) * u, 4),
                         round((w["x2"] - ox) * u, 4), round((w["y2"] - oy) * u, 4),
                         round(w["L"] * u, 4), round(ang, 3),
                         round((w["cx"] - ox) * u, 4), round((w["cy"] - oy) * u, 4),
                         round(WALL_HEIGHT_FT / w["L"], 4),
                         round(w["R"], 6), round(w["Rx"], 6),
                         round(w["Ry"], 6), round(w["m"], 1)])

    # summary: tidy Parameter,Value rows.
    summary = [
        ("Units", un),
        ("Walls used", len(walls)),
        ("Boundary", BOUNDARY),
        ("Wall height (ft)", WALL_HEIGHT_FT),
        ("Wall thickness (in)", WALL_THICK_IN),
        ("Mass mode", mode),
        ("Coords relative to", frame_desc),
        ("Origin project X", round(origin_g[0] * u, 4)),
        ("Origin project Y", round(origin_g[1] * u, 4)),
        ("X-axis angle from global X (deg)", round(xaxis_deg, 4)),
        ("Plan dim Lx", round(Lx * u, 3)),
        ("Plan dim Ly", round(Ly * u, 3)),
        ("Sum Rx", round(sRx, 6)),
        ("Sum Ry", round(sRy, 6)),
        ("X_cr", round((Xcr - ox) * u, 4)),
        ("Y_cr", round((Ycr - oy) * u, 4)),
        ("Torsional rigidity J", round(J, 6)),
        ("X_com", round((Xcom - ox) * u, 4)),
        ("Y_com", round((Ycom - oy) * u, 4)),
        ("ex = X_com - X_cr", round(ex * u, 4)),
        ("ey = Y_com - Y_cr", round(ey * u, 4)),
        ("|e|", round(e * u, 4)),
        ("Accidental e X-force (0.05*Ly)", round(eacc_x * u, 4)),
        ("Accidental e Y-force (0.05*Lx)", round(eacc_y * u, 4)),
    ]
    if dia_area is not None:
        summary.append(("Diaphragm area", round(dia_area * u * u, 3)))
    if dia_note:
        summary.append(("Note", dia_note))

    with open(summary_path, "wb") as f:
        wr = csv.writer(f)
        wr.writerow(["Parameter", "Value"])
        for k, v in summary:
            wr.writerow([k, v])

    # ---- on-screen report ---------------------------------------------------
    output.print_md("# Center of Rigidity, Mass & Eccentricity")
    output.print_md(
        "**Center of rigidity:**  X_cr = {:.4f} {u}, Y_cr = {:.4f} {u}  \n"
        "**Center of mass ({}):**  X_com = {:.4f} {u}, Y_com = {:.4f} {u}  \n"
        "**Eccentricity:**  ex = {:.4f} {u}, ey = {:.4f} {u}, |e| = {:.4f} {u}  \n"
        "**Accidental (5%):**  X-force {:.4f} {u}, Y-force {:.4f} {u}  \n"
        "Sum Rx = {:.4f}, Sum Ry = {:.4f}, J = {:.4f}  \n"
        "Walls: {} | boundary {} | h {} ft | t {} in | plan {:.2f} x {:.2f} {u}"
        .format((Xcr - ox) * u, (Ycr - oy) * u, mode,
                (Xcom - ox) * u, (Ycom - oy) * u,
                ex * u, ey * u, e * u, eacc_x * u, eacc_y * u,
                sRx, sRy, J, len(walls), BOUNDARY, WALL_HEIGHT_FT,
                WALL_THICK_IN, Lx * u, Ly * u, u=un))
    output.print_md(
        "_Frame: {} | origin (project) ({:.3f}, {:.3f}) {} | "
        "x-axis {:.3f}\u00b0 from global X._"
        .format(frame_desc, origin_g[0] * u, origin_g[1] * u, un, xaxis_deg))
    if wskip:
        output.print_md("_%d wall line(s) skipped (not straight)._" % wskip)
    if dia_note:
        output.print_md("_Note: %s._" % dia_note)
    output.print_md("Saved: `%s`" % walls_path)
    output.print_md("Saved: `%s`" % summary_path)


if __name__ == "__main__":
    main()
