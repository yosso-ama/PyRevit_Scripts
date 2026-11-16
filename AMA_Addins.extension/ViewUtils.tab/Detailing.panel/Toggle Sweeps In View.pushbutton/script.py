"""Toggle wall sweeps in the active view through the 'Walls - Sweeps' view filter.

Showing: when the view's template controls V/G filters, the view gets a copy of its
template with the sweeps on (' - SWEEPS ON'), or is released from its template, so
other views using that template are left alone.

Hiding: a view on a ' - SWEEPS ON' copy goes back to the original template, and the
copy is deleted once no view uses it; otherwise the filter is set hidden.

Hide Sweeps In Plans leaves views shown this way alone."""
from pyrevit import revit, DB, forms
from System.Collections.Generic import List

FILTER_NAME = 'Walls - Sweeps'
COPY_SUFFIX = ' - SWEEPS ON'
FILTERS_PARAM = DB.BuiltInParameter.VIS_GRAPHICS_FILTERS.value__
OPT_COPY = 'Use a copy of the template with sweeps on'
OPT_DETACH = 'Remove the view template from this view'

doc = revit.doc
view = revit.active_view

flt = [f for f in DB.FilteredElementCollector(doc).OfClass(DB.ParameterFilterElement)
       if f.Name == FILTER_NAME]
if not flt:
    forms.alert('View filter "{}" not found in this model.'.format(FILTER_NAME), exitscript=True)
fid = flt[0].Id

tpl = doc.GetElement(view.ViewTemplateId) if view.ViewTemplateId.Value > 0 else None
tpl_controls = tpl is not None and FILTERS_PARAM not in [i.Value for i in tpl.GetNonControlledTemplateParameterIds()]
owner = tpl if tpl_controls else view

if fid not in list(owner.GetFilters()):
    forms.alert('"{}" is not applied to {}, so sweeps are not hidden by it here.'.format(
        FILTER_NAME, 'its template "{}"'.format(tpl.Name) if tpl_controls else 'this view'), exitscript=True)


def template_named(name):
    found = [t for t in DB.FilteredElementCollector(doc).OfClass(DB.View) if t.IsTemplate and t.Name == name]
    return found[0] if found else None


def users_of(t):
    return [v for v in DB.FilteredElementCollector(doc).OfClass(DB.View)
            if not v.IsTemplate and v.ViewTemplateId == t.Id]


def set_sweeps(v, visible):
    if fid not in list(v.GetFilters()):
        v.AddFilter(fid)
    v.SetIsFilterEnabled(fid, True)
    v.SetFilterVisibility(fid, visible)


def hide():
    if not tpl_controls:
        with revit.Transaction('Hide Sweeps In View'):
            set_sweeps(view, False)
        return 'Sweeps are now hidden in "{}".'.format(view.Name)
    if tpl.Name.endswith(COPY_SUFFIX):
        original = template_named(tpl.Name[:-len(COPY_SUFFIX)])
        if original is not None:
            with revit.Transaction('Hide Sweeps In View'):
                view.ViewTemplateId = original.Id
                deleted = not users_of(tpl)
                if deleted:
                    doc.Delete(tpl.Id)
            return 'Sweeps are now hidden in "{}". It is back on template "{}"{}.'.format(
                view.Name, original.Name, ' and the unused copy was deleted' if deleted else '')
    others = [v for v in users_of(tpl) if v.Id != view.Id]
    if others and not forms.alert(
            'Sweeps are shown by template "{}", which {} other view(s) also use. Hide them in all of those views?'.format(
                tpl.Name, len(others)), yes=True, no=True):
        forms.alert('Nothing changed.', exitscript=True)
    with revit.Transaction('Hide Sweeps In View'):
        set_sweeps(tpl, False)
    return 'Sweeps are now hidden in template "{}".'.format(tpl.Name)


def show():
    if not tpl_controls:
        with revit.Transaction('Show Sweeps In View'):
            set_sweeps(view, True)
        return 'Sweeps are now shown in "{}".'.format(view.Name)
    others = [v for v in users_of(tpl) if v.Id != view.Id]
    choice = forms.CommandSwitchWindow.show(
        [OPT_COPY, OPT_DETACH],
        message='"{}" uses template "{}", which controls filters and is used by {} other view(s).'.format(
            view.Name, tpl.Name, len(others)))
    if not choice:
        forms.alert('Nothing changed.', exitscript=True)
    with revit.Transaction('Show Sweeps In View'):
        if choice == OPT_COPY:
            name = tpl.Name + COPY_SUFFIX
            copy = template_named(name)
            if copy is None:
                ids = DB.ElementTransformUtils.CopyElements(
                    doc, List[DB.ElementId]([tpl.Id]), doc, DB.Transform.Identity, DB.CopyPasteOptions())
                copy = doc.GetElement(list(ids)[0])
                copy.Name = name
            set_sweeps(copy, True)
            view.ViewTemplateId = copy.Id
            return 'Sweeps are now shown in "{}", which now uses template "{}".'.format(view.Name, name)
        view.ViewTemplateId = DB.ElementId.InvalidElementId
        set_sweeps(view, True)
        return 'Sweeps are now shown in "{}". It no longer uses template "{}".'.format(view.Name, tpl.Name)


shown = owner.GetIsFilterEnabled(fid) and owner.GetFilterVisibility(fid)
forms.alert(hide() if shown else show())
