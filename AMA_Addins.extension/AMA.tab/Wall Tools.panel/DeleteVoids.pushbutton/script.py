# -*- coding: utf-8 -*-
__title__ = "Delete\nVoid Instances"
"""
Delete Circular Void Instances
--------------------------------
Finds and deletes all placed instances of families whose name
starts with "CircularVoid" — leaves the family types loaded.
"""

from pyrevit import revit, DB, forms, script
from System.Collections.Generic import List

doc    = revit.doc
output = script.get_output()

FAMILY_PREFIX = "CircularVoid"

# ---------------------------------------------------------------------------
# Find all FamilyInstance elements whose family name matches the prefix
# ---------------------------------------------------------------------------
instances = []
for fi in (DB.FilteredElementCollector(doc)
           .OfClass(DB.FamilyInstance)
           .ToElements()):
    try:
        fam_name = fi.Symbol.Family.Name
        if fam_name.startswith(FAMILY_PREFIX):
            instances.append(fi)
    except Exception:
        pass

if not instances:
    forms.alert("No CircularVoid instances found in the model.")
    import sys; sys.exit()

output.print_md("**CircularVoid instances found:** {}".format(len(instances)))

# List what will be deleted
for fi in instances:
    try:
        fam_name = fi.Symbol.Family.Name
        host_id  = fi.Host.Id.Value if fi.Host else "no host"
    except Exception:
        fam_name = "unknown"
        host_id  = "unknown"
    output.print_md("  - **{}**  (id: {}  host id: {})".format(
        fam_name, fi.Id.Value, host_id))

# Confirm before deleting
confirm = forms.alert(
    "Delete {} CircularVoid instance(s)?\n\n"
    "This cannot be undone via this script (use Ctrl+Z in Revit).".format(
        len(instances)),
    ok=False,
    yes=True,
    no=True,
)

if not confirm:
    output.print_md("**Cancelled — nothing deleted.**")
    import sys; sys.exit()

# ---------------------------------------------------------------------------
# Delete instances
# ---------------------------------------------------------------------------
ids_to_delete = List[DB.ElementId]([fi.Id for fi in instances])

with revit.Transaction("Delete CircularVoid Instances"):
    deleted = doc.Delete(ids_to_delete)

output.print_md("**Done.** {} element(s) deleted.".format(len(list(deleted))))
