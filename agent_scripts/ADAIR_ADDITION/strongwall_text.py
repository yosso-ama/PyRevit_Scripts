"""Clean up text in the imported Simpson SSWH3 detail sheet (drafting view
STRONG-WALL SSWH FIRST-STORY WOOD FLOOR CONNECTION, cropped to detail 6).

DWG text came in with a substitute font: wrapped notes lost their wrapping and
the Table 6 title split.  Each bad piece is covered with a masking region and
retyped as a Revit text note; table lines under a mask are redrawn.  The
detail 7 title text that pokes into the crop is hidden by its CAD layer.
Coordinates are model feet in the drafting view (sheet drawn at 1" = 1'-0").
"""
from pyrevit.api import DB
from System import Int64

VIEW = 'STRONG-WALL SSWH FIRST-STORY WOOD FLOOR CONNECTION'
BODY_TYPE = 'AMA_DRAFTING'
TITLE_TYPE = 'Schedule Titles'
HEADER_TYPE = 'Schedule Headers'
TABLE_LINE_STYLE = '<Thin Lines>'
HIDE_LAYERS = ('SS-ANNO-TEXT-TITL',)
R = unichr(174)

MASKS = [
    ('blocking note', 21.62, 13.60, 24.70, 14.70),
    ('section note', 31.40, 8.60, 33.50, 9.02),
    ('notes', 27.84, 2.29, 33.50, 3.77),
    ('table 6 title and header', 21.55, 3.175, 27.84, 4.13),
]

TEXTS = [
    (BODY_TYPE, 24.69, 14.66, 'right', 'top',
     u'SOLID BLOCKINGS UNDER CENTER AND EACH\r'
     u'SIDE OF THE SSWH PANEL. BLOCKING TO RIM\r'
     u'JOIST WITH SDS25312. EXACT SPACING NOT\r'
     u'CRITICAL. CENTER BLOCKING\'S & SIDE\r'
     u'BLOCKING\'S SIZE AND NUMBER OF FASTENER\r'
     u'PER TABLE 4 DETAIL 7.'),
    (BODY_TYPE, 31.46, 8.98, 'left', 'top',
     u'SOLID BLOCKINGS UNDER\r'
     u'STRONG-WALL' + R + u'\r'
     u'HIGH-STRENGTH STEEL\r'
     u'SHEARWALL. TOTAL\r'
     u'THICKNESS OF RIM JOIST\r'
     u'AND SOLID BLOCKING\r'
     u'SHALL BE SUFFICIENT TO\r'
     u'PROVIDE FULL BEARING\r'
     u'BENEATH THE SSWH.'),
    (BODY_TYPE, 27.90, 3.73, 'left', 'top',
     u'NOTES:\r'
     u'1.  USE WOOD FIRST-FLOOR ALLOWABLE LOAD TABLES IN THE EVALUATION\r'
     u'     REPORT FOR THIS INSTALLATION.\r'
     u'2.  USE ALTERNATE DETAIL 5/SSWH2 TO ACHIEVE MAXIMUM ON-CONCRETE\r'
     u'     ALLOWABLE LOADS.\r'
     u'3.  FOR TWO-STORY STACKED STRONG-WALL HIGH-STRENGTH STEEL\r'
     u'     SHEARWALLS WITH WOOD FIRST FLOOR, USE ALTERNATE DETAIL 5/SSWH2.\r'
     u'4.  DESIGNER SHALL DESIGN FOR SHEAR TRANSFER FROM RIM JOIST TO SILL\r'
     u'     PLATE AND SILL PLATE TO FOUNDATION.'),
    (TITLE_TYPE, 21.60, 4.10, 'left', 'top',
     u'TABLE 6: FIRST-STORY WOOD FLOOR CONNECTION KIT'),
    (HEADER_TYPE, 22.252, 3.47, 'center', 'middle', u'WALL WIDTH\r(in.)'),
    (HEADER_TYPE, 23.573, 3.47, 'center', 'middle', u'MODEL\rNO.'),
    (HEADER_TYPE, 26.014, 3.47, 'center', 'middle', u'CONTENTS'),
]

TABLE_LINES = [
    (21.588, 3.777, 27.798, 3.777),
    (21.588, 3.162, 21.588, 3.777),
    (22.916, 3.162, 22.916, 3.777),
    (24.229, 3.162, 24.229, 3.777),
    (27.798, 3.162, 27.798, 3.777),
]

H = {'left': DB.HorizontalTextAlignment.Left, 'center': DB.HorizontalTextAlignment.Center,
     'right': DB.HorizontalTextAlignment.Right}
V = {'top': DB.VerticalTextAlignment.Top, 'middle': DB.VerticalTextAlignment.Middle}


def a(x):
    return ''.join(c if ord(c) < 128 else '?' for c in unicode(x or ''))


def name_of(e):
    return e.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString()


def view(doc):
    return [v for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewDrafting) if v.Name == VIEW][0]


def text_type(doc, name):
    return [t for t in DB.FilteredElementCollector(doc).OfClass(DB.TextNoteType) if name_of(t) == name][0]


def line_style(doc, name):
    for i in DB.FilledRegion.GetValidLineStyleIdsForFilledRegion(doc):
        if doc.GetElement(i).Name == name:
            return doc.GetElement(i)
    cat = doc.Settings.Categories.get_Item(DB.BuiltInCategory.OST_Lines)
    for c in cat.SubCategories:
        if c.Name == name:
            return c.GetGraphicsStyle(DB.GraphicsStyleType.Projection)
    return None


def rect(x0, y0, x1, y1):
    p = [DB.XYZ(x0, y0, 0), DB.XYZ(x1, y0, 0), DB.XYZ(x1, y1, 0), DB.XYZ(x0, y1, 0)]
    loop = DB.CurveLoop()
    for i in range(4):
        loop.Append(DB.Line.CreateBound(p[i], p[(i + 1) % 4]))
    return loop


def imports_in(doc, v):
    return [i for i in DB.FilteredElementCollector(doc, v.Id).OfClass(DB.ImportInstance)]


def apply(doc):
    """Call inside a transaction.  Returns a summary."""
    v = view(doc)
    out = {'view': v.Id.Value, 'hidden_layers': [], 'masks': [], 'texts': [], 'lines': []}
    for inst in imports_in(doc, v):
        p = inst.get_Parameter(DB.BuiltInParameter.IMPORT_BACKGROUND)
        if p and not p.IsReadOnly:
            p.Set(1)
        for c in inst.Category.SubCategories:
            if c.Name in HIDE_LAYERS and v.CanCategoryBeHidden(c.Id):
                v.SetCategoryHidden(c.Id, True)
                out['hidden_layers'].append(c.Name)
    invisible = line_style(doc, '<Invisible lines>')
    for label, x0, y0, x1, y1 in MASKS:
        m = DB.FilledRegion.CreateMaskingRegion(doc, v.Id, [rect(x0, y0, x1, y1)])
        if invisible is not None:
            m.SetLineStyleId(invisible.Id)
        out['masks'].append([label, m.Id.Value])
    ls = line_style(doc, TABLE_LINE_STYLE)
    for x0, y0, x1, y1 in TABLE_LINES:
        dc = doc.Create.NewDetailCurve(v, DB.Line.CreateBound(DB.XYZ(x0, y0, 0), DB.XYZ(x1, y1, 0)))
        if ls is not None:
            dc.LineStyle = ls
        out['lines'].append(dc.Id.Value)
    for tname, x, y, h, vert, txt in TEXTS:
        o = DB.TextNoteOptions(text_type(doc, tname).Id)
        o.HorizontalAlignment = H[h]
        o.VerticalAlignment = V[vert]
        tn = DB.TextNote.Create(doc, v.Id, DB.XYZ(x, y, 0), txt, o)
        if txt.startswith(u'NOTES:'):
            ft = tn.GetFormattedText()
            ft.SetUnderlineStatus(DB.TextRange(0, 6), True)
            tn.SetFormattedText(ft)
        out['texts'].append([a(txt.split(u'\r')[0]), tn.Id.Value])
    return out
