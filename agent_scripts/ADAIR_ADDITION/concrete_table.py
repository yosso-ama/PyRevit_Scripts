"""Minimum concrete strength table (IRC R402.2 style) drawn in a drafting view with
detail lines, text notes and a gray filled-region header band, grouped as one
detail group.  Sizes are paper inches; they are multiplied by the view scale.
"""
from pyrevit.api import DB
from System.Collections.Generic import List

TITLE = 'CONCRETE STRENGTH TABLE'
COLS = [4.50, 1.25]              # paper inches
HEADER_H = 0.20
ROW_H = 0.34
PAD_X, PAD_Y = 0.06, 0.02
HEADER = ['TYPE OR LOCATION OF CONCRETE CONSTRUCTION', "MIN f'c"]
ROWS = [
    ['BASEMENT WALLS, FOUNDATIONS, AND OTHER CONCRETE\rNOT EXPOSED TO THE WEATHER', '2,500 PSI'],
    ['BASEMENT SLABS AND INTERIOR SLABS ON GRADE,\rEXCEPT GARAGE FLOOR SLABS', '2,500 PSI'],
    ['BASEMENT WALLS, FOUNDATION WALLS, EXTERIOR WALLS,\rAND OTHER VERTICAL CONCRETE WORK EXPOSED TO THE WEATHER', '3,000 PSI'],
    ['PORCHES, CARPORT SLABS, AND STEPS EXPOSED TO THE\rWEATHER, AND GARAGE FLOOR SLABS', '3,500 PSI'],
]


def tname(e):
    p = e.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
    return p.AsString() if p else None


def line_style(doc, names=('Thin Lines', '<Thin Lines>', 'Medium Lines')):
    cats = doc.Settings.Categories.get_Item(DB.BuiltInCategory.OST_Lines).SubCategories
    for n in names:
        for c in cats:
            if c.Name == n:
                return c.GetGraphicsStyle(DB.GraphicsStyleType.Projection)
    return None


def gray_fill(doc):
    for t in DB.FilteredElementCollector(doc).OfClass(DB.FilledRegionType):
        n = (tname(t) or '').upper()
        if 'GRAY' in n or 'GREY' in n:
            return t
    return None


def build(doc, view, origin, text_type_id, fill_type=None):
    """Draw the table with its top-left corner at origin (model XYZ in the view).
    Returns the new group and a summary."""
    s = float(view.Scale) / 12.0
    x0, y0 = origin.X, origin.Y
    xs = [x0]
    for w in COLS:
        xs.append(xs[-1] + w * s)
    ys = [y0, y0 - HEADER_H * s]
    for _ in ROWS:
        ys.append(ys[-1] - ROW_H * s)
    ids = []
    gs = line_style(doc)

    def seg(p, q):
        dc = doc.Create.NewDetailCurve(view, DB.Line.CreateBound(p, q))
        if gs is not None:
            dc.LineStyle = gs
        ids.append(dc.Id)

    for y in ys:
        seg(DB.XYZ(xs[0], y, 0), DB.XYZ(xs[-1], y, 0))
    for x in xs:
        seg(DB.XYZ(x, ys[0], 0), DB.XYZ(x, ys[-1], 0))

    if fill_type is not None:
        loop = DB.CurveLoop()
        pts = [DB.XYZ(xs[0], ys[0], 0), DB.XYZ(xs[-1], ys[0], 0), DB.XYZ(xs[-1], ys[1], 0), DB.XYZ(xs[0], ys[1], 0)]
        for p, q in zip(pts, pts[1:] + pts[:1]):
            loop.Append(DB.Line.CreateBound(p, q))
        fr = DB.FilledRegion.Create(doc, fill_type.Id, view.Id, List[DB.CurveLoop]([loop]))
        ids.append(fr.Id)

    def note(col, top, text, bold=False, center=False):
        opts = DB.TextNoteOptions(text_type_id)
        opts.HorizontalAlignment = DB.HorizontalTextAlignment.Center if center else DB.HorizontalTextAlignment.Left
        opts.VerticalAlignment = DB.VerticalTextAlignment.Top
        width = ((xs[col + 1] - xs[col]) - 2 * PAD_X * s) / view.Scale    # TextNote width is in paper feet
        x = (xs[col] + xs[col + 1]) / 2.0 if center else xs[col] + PAD_X * s
        n = DB.TextNote.Create(doc, view.Id, DB.XYZ(x, top - PAD_Y * s, 0), width, text, opts)
        ft = n.GetFormattedText()
        if bold:
            ft.SetBoldStatus(True)
        k = text.find("f'c")
        if k >= 0:
            ft.SetSubscriptStatus(DB.TextRange(k + 2, 1), True)
        n.SetFormattedText(ft)
        ids.append(n.Id)
        return n

    for c, h in enumerate(HEADER):
        note(c, ys[0], h, bold=True, center=(c == 1))
    for r, row in enumerate(ROWS):
        for c, txt in enumerate(row):
            note(c, ys[r + 1], txt, center=(c == 1))

    doc.Regenerate()
    g = doc.Create.NewGroup(List[DB.ElementId](ids))
    gt = doc.GetElement(g.GetTypeId())
    names = set(tname(t) for t in DB.FilteredElementCollector(doc).OfClass(DB.GroupType))
    name, k = TITLE, 2
    while name in names:
        name = '%s %d' % (TITLE, k)
        k += 1
    gt.Name = name
    return g, {'group': [g.Id.Value, name], 'size_paper_in': [round(sum(COLS), 3), round(HEADER_H + ROW_H * len(ROWS), 3)],
               'size_model_ft': [round(xs[-1] - xs[0], 3), round(ys[0] - ys[-1], 3)], 'elements': len(ids),
               'line_style': gs.GraphicsStyleCategory.Name if gs is not None else None,
               'fill': tname(fill_type) if fill_type is not None else None}


GRAY_NAME = 'Solid Gray 15%'


def gray_fill_or_create(doc):
    """Existing gray fill type, else a duplicate of Solid Black in light gray."""
    t = gray_fill(doc)
    if t is not None:
        return t, False
    black = [x for x in DB.FilteredElementCollector(doc).OfClass(DB.FilledRegionType) if tname(x) == 'Solid Black'][0]
    t = black.Duplicate(GRAY_NAME)
    t.ForegroundPatternColor = DB.Color(217, 217, 217)
    return t, True
