"""Hide cut and surface fill patterns (foreground and background) for walls,
floors, structural foundations and slab edges in plan view templates, so plans
show outlines only.  Sections and materials are not touched.
"""
from pyrevit.api import DB

TEMPLATES = ('STR FOUNDATION PLAN (PROPOSED)', 'STR FOUNDATION PLAN (ORIGINAL)')
CATEGORIES = (DB.BuiltInCategory.OST_Walls, DB.BuiltInCategory.OST_Floors,
              DB.BuiltInCategory.OST_StructuralFoundation, DB.BuiltInCategory.OST_EdgeSlab)


def a(x):
    return ''.join(c if ord(c) < 128 else '?' for c in unicode(x or ''))


def state(o):
    return [o.IsCutForegroundPatternVisible, o.IsCutBackgroundPatternVisible,
            o.IsSurfaceForegroundPatternVisible, o.IsSurfaceBackgroundPatternVisible]


def hide_patterns(doc, names=TEMPLATES):
    """Returns {template: {category: [before, after]}} with the four pattern
    visibility flags (cut fg, cut bg, surface fg, surface bg)."""
    out = {}
    tpls = dict((a(t.Name), t) for t in DB.FilteredElementCollector(doc).OfClass(DB.View) if t.IsTemplate)
    for n in names:
        t = tpls.get(n)
        if t is None:
            out[n] = 'not found'
            continue
        res = {}
        for bic in CATEGORIES:
            cid = DB.ElementId(bic)
            o = t.GetCategoryOverrides(cid)
            before = state(o)
            o.SetCutForegroundPatternVisible(False)
            o.SetCutBackgroundPatternVisible(False)
            o.SetSurfaceForegroundPatternVisible(False)
            o.SetSurfaceBackgroundPatternVisible(False)
            t.SetCategoryOverrides(cid, o)
            res[a(doc.Settings.Categories.get_Item(bic).Name)] = [before, state(t.GetCategoryOverrides(cid))]
        out[n] = res
    return out
