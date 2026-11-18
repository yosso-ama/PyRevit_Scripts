"""Invert tags on the foundation drains in the PROPOSED foundation plan.

Re-references the drain pipes to FFE (EXISTING) so Upper/Lower End Invert
Elevation read as project elevations (pipes do not move), then places
DRAIN INV HIGH at each run's high end and DRAIN INV LOW at each run's daylight
outlet and at the low end of each run's perforated pipe.
"""
from pyrevit.api import DB
import foundation_drain as fd

DATUM = 'FFE (EXISTING)'
PLAN = 'FOUNDATION PLAN (PROPOSED)'
HIGH_TAG, LOW_TAG = 'DRAIN INV HIGH', 'DRAIN INV LOW'
OFFSET = 3.0


def a(x):
    return ''.join(c if ord(c) < 128 else '?' for c in unicode(x or ''))


def tag_symbol(doc, family):
    for s in DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol).OfCategory(DB.BuiltInCategory.OST_PipeTags):
        if s.FamilyName == family:
            return s
    return None


def plan_view(doc):
    return [v for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewPlan)
            if not v.IsTemplate and PLAN in a(v.Name)][0]


def ends(p):
    c = p.Location.Curve
    e0, e1 = c.GetEndPoint(0), c.GetEndPoint(1)
    return (e0, e1) if e0.Z >= e1.Z else (e1, e0)


def rereference(doc, pipes):
    lvl = [l for l in DB.FilteredElementCollector(doc).OfClass(DB.Level) if l.Name == DATUM][0]
    moved = []
    for p in pipes:
        before = ends(p)
        p.get_Parameter(DB.BuiltInParameter.RBS_START_LEVEL_PARAM).Set(lvl.Id)
        doc.Regenerate()
        after = ends(p)
        if any(b.DistanceTo(c) > 1e-6 for b, c in zip(before, after)):
            moved.append(p.Id.Value)
    return moved


def targets(pipes):
    """(pipe, end point, 'HIGH' or 'LOW', label) per run."""
    runs = {}
    for p in pipes:
        name =(p.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).AsString() or '').replace(' OUTLET', '')
        runs.setdefault(name, []).append(p)
    out = []
    for name, ps in sorted(runs.items()):
        hi = max(ps, key=lambda p: ends(p)[0].Z)
        out.append((hi, ends(hi)[0], 'HIGH', name + ' high end'))
        perf = [p for p in ps if not (p.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).AsString() or '').endswith('OUTLET')]
        lo = min(perf, key=lambda p: ends(p)[1].Z)
        out.append((lo, ends(lo)[1], 'LOW', name + ' end of perforated'))
        outs = [p for p in ps if p not in perf]
        for o in outs:
            out.append((o, ends(o)[1], 'LOW', name + ' daylight outlet'))
    return out


def place(doc, view, high_sym, low_sym, pipes):
    tags = []
    for p, e, kind, label in targets(pipes):
        sym = high_sym if kind == 'HIGH' else low_sym
        if not sym.IsActive:
            sym.Activate()
            doc.Regenerate()
        c = p.Location.Curve
        d = (c.GetEndPoint(1) - c.GetEndPoint(0)).Normalize()
        head = DB.XYZ(e.X + d.Y * OFFSET, e.Y - d.X * OFFSET, e.Z)
        ref = DB.Reference(p)
        tg = DB.IndependentTag.Create(doc, sym.Id, view.Id, ref, True, DB.TagOrientation.Horizontal, head)
        try:
            tg.LeaderEndCondition = DB.LeaderEndCondition.Free
            tg.SetLeaderEnd(ref, e)
        except Exception:
            pass
        tags.append([label, kind, tg.Id.Value, a(tg.TagText)])
    return tags
