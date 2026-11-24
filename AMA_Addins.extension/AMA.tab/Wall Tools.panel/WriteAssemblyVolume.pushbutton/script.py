# -*- coding: utf-8 -*-
__title__ = "Write\nVolume"
"""
Write Wall Volume to Existing Assemblies
-----------------------------------------
Finds all Assembly Instances in the model, sums the volume of any
Wall members, and writes the total to the "Total Wall Volume" parameter.
"""

from pyrevit import revit, DB, forms, script
from System.Collections.Generic import List

doc    = revit.doc
output = script.get_output()

PARAM_NAME = "Total Wall Volume"

# ---------------------------------------------------------------------------
# Collect all assemblies
# ---------------------------------------------------------------------------
assemblies = list(
    DB.FilteredElementCollector(doc)
    .OfClass(DB.AssemblyInstance)
    .ToElements()
)

if not assemblies:
    forms.alert("No assemblies found in the model.", exitscript=True)

output.print_md("**Assemblies found:** {}".format(len(assemblies)))

# ---------------------------------------------------------------------------
# Process each assembly
# ---------------------------------------------------------------------------
updated   = 0
no_param  = 0
no_walls  = 0

for assembly in assemblies:
    try:
        asm_name = assembly.AssemblyTypeName
    except Exception:
        asm_name = "id:{}".format(assembly.Id.Value)

    output.print_md("\n---\n**Assembly:** {}".format(asm_name))

    # Check parameter exists and is writable
    vol_param = assembly.LookupParameter(PARAM_NAME)

    if vol_param is None:
        output.print_md("  ✗ Parameter '{}' not found — dumping all parameters:".format(
            PARAM_NAME))
        for p in assembly.Parameters:
            try:
                pname = p.Definition.Name if p.Definition else "?"
                ptype = str(p.StorageType)
                ro    = p.IsReadOnly
                output.print_md("    **{}** | {} | readOnly={}".format(pname, ptype, ro))
            except Exception:
                pass
        no_param += 1
        continue

    output.print_md("  Parameter found | readOnly={}".format(vol_param.IsReadOnly))

    # Get member IDs and find walls
    member_ids = assembly.GetMemberIds()
    wall_vol_cf = 0.0
    wall_count  = 0

    for eid in member_ids:
        elem = doc.GetElement(eid)
        if isinstance(elem, DB.Wall):
            p = elem.get_Parameter(DB.BuiltInParameter.HOST_VOLUME_COMPUTED)
            if p:
                wall_vol_cf += p.AsDouble()
                wall_count  += 1

    output.print_md("  Wall members: {}  |  Total volume: {:.3f} CF".format(
        wall_count, wall_vol_cf))

    if wall_count == 0:
        no_walls += 1
        continue

    # Write volume
    with revit.Transaction("Write Volume - {}".format(asm_name)):
        if not vol_param.IsReadOnly:
            vol_param.Set(wall_vol_cf)
            output.print_md("  ✓ Written: **{:.3f} CF**".format(wall_vol_cf))
        else:
            output.print_md("  ✗ Parameter is read-only — cannot write.")
            no_param += 1
            continue

    updated += 1

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
output.print_md(
    "\n---\n**Summary**\n"
    "- Assemblies updated: {}\n"
    "- Parameter not found/read-only: {}\n"
    "- Assemblies with no wall members: {}".format(
        updated, no_param, no_walls
    )
)
