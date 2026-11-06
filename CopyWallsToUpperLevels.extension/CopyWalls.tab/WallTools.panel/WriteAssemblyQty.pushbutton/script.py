# -*- coding: utf-8 -*-
__title__ = "Write\nQty"
"""
Write Quantity and Unit Volume to Assemblies
---------------------------------------------
For assemblies whose name matches a user-supplied prefix:
  - Writes Quantity = 1 (integer) to each assembly instance
  - Unit Volume is already stored as "Total Wall Volume" per assembly
    so the schedule can calculate Quantity * Total Wall Volume

Requires two shared parameters to already be bound to Assembly Instance:
  - "Total Wall Volume"  (Volume)   — written by Write Volume button
  - "Quantity"           (Integer)  — bound and written by this script
"""

import os
from pyrevit import revit, DB, forms, script

doc    = revit.doc
app    = doc.Application

QUANTITY_PARAM = "Quantity"
VOLUME_PARAM   = "Total Wall Volume"
SP_GROUP_NAME  = "Wall Assembly Parameters"
DEFAULT_SP     = r"Y:\CIVIL_CAD\REVIT_FILES\PARAMETERS\AMA_CIVIL_SHARED_PARAMS.txt"

# ---------------------------------------------------------------------------
# STEP 1 – User inputs
# ---------------------------------------------------------------------------
prefix = forms.ask_for_string(
    prompt="Assembly name prefix to match (e.g. 'VAULT'):",
    title="Assembly Name Prefix",
    default="VAULT"
)
if not prefix:
    import sys; sys.exit()
prefix = prefix.strip()

sp_path = forms.ask_for_string(
    prompt="Full path to your shared parameter file (.txt):",
    title="Shared Parameter File",
    default=DEFAULT_SP
)
if not sp_path:
    import sys; sys.exit()
sp_path = sp_path.strip()

if not os.path.exists(sp_path):
    forms.alert("File not found:\n{}".format(sp_path), exitscript=True)

output = script.get_output()
output.print_md("**Prefix filter:** {}".format(prefix))
output.print_md("**Shared parameter file:** {}".format(sp_path))

# ---------------------------------------------------------------------------
# STEP 2 – Ensure Quantity shared parameter is bound to Assembly Instance
# ---------------------------------------------------------------------------
def ensure_param_bound(param_name, spec_type_id):
    """
    Finds or creates a shared parameter definition and binds it
    to the Assembly Instance category. Returns the definition.
    """
    orig_sp = None
    try:
        orig_sp = app.SharedParametersFilename
    except Exception:
        pass

    app.SharedParametersFilename = sp_path
    sp_file = app.OpenSharedParameterFile()

    if sp_file is None:
        forms.alert("Could not open shared parameter file.", exitscript=True)

    # Find or create group
    sp_group = None
    for g in sp_file.Groups:
        if g.Name == SP_GROUP_NAME:
            sp_group = g
            break
    if sp_group is None:
        sp_group = sp_file.Groups.Create(SP_GROUP_NAME)

    # Find or create definition
    ext_def = None
    for d in sp_group.Definitions:
        if d.Name == param_name:
            ext_def = d
            break
    if ext_def is None:
        def_opts = DB.ExternalDefinitionCreationOptions(param_name, spec_type_id)
        def_opts.UserModifiable = True
        ext_def = sp_group.Definitions.Create(def_opts)
        output.print_md("  Created parameter definition: **{}**".format(param_name))
    else:
        output.print_md("  Found parameter definition: **{}**".format(param_name))

    # Check if already bound
    it = doc.ParameterBindings.ForwardIterator()
    already_bound = False
    while it.MoveNext():
        try:
            if it.Key.Name == param_name:
                already_bound = True
                break
        except Exception:
            pass

    if not already_bound:
        asm_cat = doc.Settings.Categories.get_Item(DB.BuiltInCategory.OST_Assemblies)
        cat_set = DB.CategorySet()
        cat_set.Insert(asm_cat)
        binding = DB.InstanceBinding(cat_set)
        with revit.Transaction("Bind Param - {}".format(param_name)):
            doc.ParameterBindings.Insert(ext_def, binding)
        output.print_md("  Bound **{}** to Assembly Instance.".format(param_name))
    else:
        output.print_md("  **{}** already bound.".format(param_name))

    if orig_sp:
        try:
            app.SharedParametersFilename = orig_sp
        except Exception:
            pass

    return ext_def

output.print_md("\n**Setting up shared parameters...**")
ensure_param_bound(QUANTITY_PARAM, DB.SpecTypeId.Int.Integer)

# ---------------------------------------------------------------------------
# STEP 3 – Collect assemblies matching prefix
# ---------------------------------------------------------------------------
all_assemblies = list(
    DB.FilteredElementCollector(doc)
    .OfClass(DB.AssemblyInstance)
    .ToElements()
)

matched = []
for asm in all_assemblies:
    try:
        name = asm.AssemblyTypeName
        if name and name.startswith(prefix):
            matched.append(asm)
    except Exception:
        pass

output.print_md("\n**Assemblies matching prefix '{}':** {}".format(prefix, len(matched)))

if not matched:
    forms.alert("No assemblies found matching prefix '{}'.".format(prefix),
                exitscript=True)

# ---------------------------------------------------------------------------
# STEP 4 – Write Quantity = 1 to each matched assembly
# ---------------------------------------------------------------------------
updated  = 0
no_param = 0

for asm in matched:
    try:
        name = asm.AssemblyTypeName
    except Exception:
        name = "id:{}".format(asm.Id.Value)

    qty_param = asm.LookupParameter(QUANTITY_PARAM)
    vol_param = asm.LookupParameter(VOLUME_PARAM)

    vol_val = vol_param.AsDouble() if vol_param else 0.0

    if qty_param is None:
        output.print_md("  ✗ **{}** — Quantity parameter not found.".format(name))
        no_param += 1
        continue

    if qty_param.IsReadOnly:
        output.print_md("  ✗ **{}** — Quantity parameter is read-only.".format(name))
        no_param += 1
        continue

    with revit.Transaction("Write Quantity - {}".format(name)):
        qty_param.Set(1)

    output.print_md("  ✓ **{}** | Qty=1 | Volume={:.3f} CF".format(name, vol_val))
    updated += 1

# ---------------------------------------------------------------------------
# STEP 5 – Summary and schedule instructions
# ---------------------------------------------------------------------------
output.print_md(
    "\n---\n**Summary**\n"
    "- Assemblies updated: {}\n"
    "- Parameter not found/read-only: {}".format(updated, no_param)
)

output.print_md(
    "\n---\n**Next: Add to Schedule**\n"
    "1. Open your Assembly schedule\n"
    "2. Schedule Properties → Fields → add **Quantity** and **Total Wall Volume**\n"
    "3. Add a Calculated Value: `Total Volume by Type` = `Quantity * Total Wall Volume`\n"
    "4. Sorting/Grouping → sort by Assembly Type → enable Footer totals\n"
    "5. The footer will sum Quantity (count) and total volume per type"
)
