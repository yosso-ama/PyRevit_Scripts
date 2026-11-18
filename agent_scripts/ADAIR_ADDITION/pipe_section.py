"""Yin-yang pipe-in-section symbol on the foundation drains.

Builds a PIPE SECTION - YIN YANG detail item (circle at the pipe OD with the
S-curve, origin at the centre) from the Detail Item template, loads it, and places
one wherever a section or detail view cuts a FOUNDATION DRAIN pipe square inside
its crop.  Placed symbols carry the comment AUTO PIPE YY.
"""
import math
from pyrevit.api import DB
from Autodesk.Revit.DB import Plumbing

DETAIL_RFT = r'C:\ProgramData\Autodesk\RVT 2026\Family Templates\English-Imperial\Detail Item.rft'
FAMILY, TYPE = 'PIPE SECTION - YIN YANG', '4"'
OD = 4.5 / 12                     # 4" PVC outside diameter
TAG = 'AUTO PIPE YY'
DRAIN = 'FOUNDATION DRAIN'
SQUARE_TOL = 0.98
SECTION_TYPES = (DB.ViewType.Section, DB.ViewType.Detail)


def tname(e):
    p = e.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
    return p.AsString() if p else None


def comment(e):
    p = e.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    return (p.AsString() or '') if p else ''


def symbol(doc):
    for s in DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol).OfCategory(DB.BuiltInCategory.OST_DetailComponents):
        if s.FamilyName == FAMILY:
            return s
    return None


def build_family(doc, app):
    """Create and load the symbol family (call with no open transaction in doc)."""
    s = symbol(doc)
    if s is not None:
        return s, False
    fam_doc = app.NewFamilyDocument(DETAIL_RFT)
    try:
        view = [v for v in DB.FilteredElementCollector(fam_doc).OfClass(DB.ViewPlan) if not v.IsTemplate][0]
        t = DB.Transaction(fam_doc, 'yin yang')
        t.Start()
        r = OD / 2.0
        c = DB.XYZ.Zero
        arcs = [DB.Arc.Create(c, r, 0.0, math.pi, DB.XYZ.BasisX, DB.XYZ.BasisY),
                DB.Arc.Create(c, r, math.pi, 2 * math.pi, DB.XYZ.BasisX, DB.XYZ.BasisY),
                DB.Arc.Create(DB.XYZ(0, r / 2.0, 0), r / 2.0, math.pi / 2.0, 3 * math.pi / 2.0, DB.XYZ.BasisX, DB.XYZ.BasisY),
                DB.Arc.Create(DB.XYZ(0, -r / 2.0, 0), r / 2.0, -math.pi / 2.0, math.pi / 2.0, DB.XYZ.BasisX, DB.XYZ.BasisY)]
        for a in arcs:
            fam_doc.FamilyCreate.NewDetailCurve(view, a)
        t.Commit()
        fam = fam_doc.LoadFamily(doc)
    finally:
        fam_doc.Close(False)
    t = DB.Transaction(doc, 'name yin yang')
    t.Start()
    fam.Name = FAMILY
    s = doc.GetElement(list(fam.GetFamilySymbolIds())[0])
    s.Name = TYPE
    t.Commit()
    return s, True


def drains(doc):
    return [p for p in DB.FilteredElementCollector(doc).OfClass(Plumbing.Pipe) if comment(p).startswith(DRAIN)]


def cuts(doc, view, pipes):
    """Pipe centre points where the view's cut plane crosses a drain pipe square on,
    inside the crop."""
    out = []
    o, n = view.Origin, view.ViewDirection
    crop = view.CropBox
    inv = crop.Transform.Inverse
    for p in pipes:
        c = p.Location.Curve
        p0, p1 = c.GetEndPoint(0), c.GetEndPoint(1)
        d0, d1 = (p0 - o).DotProduct(n), (p1 - o).DotProduct(n)
        if d0 * d1 > 0 or abs(d0 - d1) < 1e-9:
            continue
        if abs((p1 - p0).Normalize().DotProduct(n)) < SQUARE_TOL:
            continue
        x = p0 + (p1 - p0) * (d0 / (d0 - d1))
        loc = inv.OfPoint(x)
        if view.CropBoxActive and not (crop.Min.X <= loc.X <= crop.Max.X and crop.Min.Y <= loc.Y <= crop.Max.Y):
            continue
        out.append((p, x))
    return out


def place(doc, sym):
    """Place the symbol at every drain cut in every section; skip cuts that already
    have one within 0.05 ft (call inside a transaction)."""
    if not sym.IsActive:
        sym.Activate()
        doc.Regenerate()
    pipes = drains(doc)
    placed, kept = [], []
    for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewSection):
        if v.IsTemplate or v.ViewType not in SECTION_TYPES:
            continue
        have = [e for e in DB.FilteredElementCollector(doc, v.Id).OfClass(DB.FamilyInstance)
                if e.Symbol.Id == sym.Id and e.OwnerViewId == v.Id]
        for p, x in cuts(doc, v, pipes):
            if any(e.Location.Point.DistanceTo(x) < 0.05 for e in have):
                kept.append(v.Name)
                continue
            inst = doc.Create.NewFamilyInstance(x, sym, v)
            inst.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).Set(TAG)
            placed.append([v.Name, comment(p), inst.Id.Value])
    return placed, kept
