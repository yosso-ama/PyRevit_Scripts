"""Enable the 'Walls - Sweeps' view filter, set to hidden, in every plan view and
plan template that has it applied.  Views whose template controls V/G filters are
handled through the template.  Sections and elevations are not touched.  A view or
template where the filter is enabled and set visible was shown on purpose (Show
Sweeps In View) and is left alone."""
from pyrevit import revit, DB, forms

FILTER_NAME = 'Walls - Sweeps'
PLAN_TYPES = (DB.ViewType.FloorPlan, DB.ViewType.CeilingPlan,
              DB.ViewType.EngineeringPlan, DB.ViewType.AreaPlan)
FILTERS_PARAM = DB.BuiltInParameter.VIS_GRAPHICS_FILTERS.value__

doc = revit.doc
flt = [f for f in DB.FilteredElementCollector(doc).OfClass(DB.ParameterFilterElement)
       if f.Name == FILTER_NAME]
if not flt:
    forms.alert('View filter "{}" not found in this model.'.format(FILTER_NAME), exitscript=True)
fid = flt[0].Id

def label(v):
    return '{}{}'.format(v.Name, ' (template)' if v.IsTemplate else '')


targets, shown = [], []
for v in DB.FilteredElementCollector(doc).OfClass(DB.View):
    if v.ViewType not in PLAN_TYPES or fid not in list(v.GetFilters()):
        continue
    if not v.IsTemplate and v.ViewTemplateId.Value > 0:
        tpl = doc.GetElement(v.ViewTemplateId)
        if FILTERS_PARAM not in [i.Value for i in tpl.GetNonControlledTemplateParameterIds()]:
            continue
    if v.GetIsFilterEnabled(fid):
        if v.GetFilterVisibility(fid):
            shown.append(label(v))
        continue
    targets.append(v)

kept = '\n\nLeft showing sweeps (set by Show Sweeps In View):\n\n' + '\n'.join(sorted(shown)) if shown else ''
if not targets:
    forms.alert('"{}" is already enabled and hidden in every plan that uses it.{}'.format(FILTER_NAME, kept))
else:
    with revit.Transaction('Hide Sweeps In Plans'):
        for v in targets:
            v.SetIsFilterEnabled(fid, True)
            v.SetFilterVisibility(fid, False)
    forms.alert('"{}" enabled and hidden in:\n\n{}{}'.format(FILTER_NAME, '\n'.join(sorted(label(v) for v in targets)), kept))
