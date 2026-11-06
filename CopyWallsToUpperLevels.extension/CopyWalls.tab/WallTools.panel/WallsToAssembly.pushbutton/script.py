# -*- coding: utf-8 -*-
__title__ = "Walls to\nAssembly"
"""
Create Wall Assemblies by Level with Total Wall Volume
-------------------------------------------------------
User selects start and end levels and provides a base name.
Script creates one Assembly per level containing all structural walls,
named: <BaseName> - <LevelName>
Computes total wall volume (CF) and writes to a shared parameter.
"""

import os
from pyrevit import revit, DB, forms, script
from System.Collections.Generic import List

doc   = revit.doc
uidoc = revit.uidoc
app   = doc.Application

PARAM_NAME  = "Total Wall Volume"
# Parameter group handled at bind time
SP_GROUP_NAME = "Wall Assembly Parameters"

# ---------------------------------------------------------------------------
# STEP 1 – Collect and sort levels
# ---------------------------------------------------------------------------
all_levels = sorted(
    DB.FilteredElementCollector(doc).OfClass(DB.Level).ToElements(),
    key=lambda l: l.Elevation
)

if not all_levels:
    forms.alert("No levels found in the model.", exitscript=True)

level_names = [l.Name for l in all_levels]

# ---------------------------------------------------------------------------
# STEP 2 – User selects start and end levels
# ---------------------------------------------------------------------------
selected = forms.SelectFromList.show(
    level_names,
    title="Select Start and End Levels",
    message="Select exactly two levels (start and end, inclusive).\n"
            "Hold Ctrl to select multiple.",
    multiselect=True,
)

if not selected or len(selected) != 2:
    forms.alert("Please select exactly two levels.", exitscript=True)

sel_levels    = sorted([l for l in all_levels if l.Name in selected],
                       key=lambda l: l.Elevation)
start_level   = sel_levels[0]
end_level     = sel_levels[1]
start_idx     = all_levels.index(start_level)
end_idx       = all_levels.index(end_level)
target_levels = all_levels[start_idx:end_idx + 1]

# ---------------------------------------------------------------------------
# STEP 3 – User enters base name
# ---------------------------------------------------------------------------
base_name = forms.ask_for_string(
    prompt="Assembly name prefix.\nFinal name will be: <prefix> - <Level Name>",
    title="Assembly Base Name",
    default="Wall Assembly"
)

if not base_name:
    import sys; sys.exit()
base_name = base_name.strip()

# ---------------------------------------------------------------------------
# STEP 4 – User provides shared parameter file path
# ---------------------------------------------------------------------------
sp_path = forms.ask_for_string(
    prompt="Full path to your shared parameter file (.txt):",
    title="Shared Parameter File Path",
    default=r"Y:\CIVIL_CAD\REVIT_FILES\PARAMETERS\AMA_CIVIL_SHARED_PARAMS.txt"
)

if not sp_path:
    import sys; sys.exit()
sp_path = sp_path.strip()

if not os.path.exists(sp_path):
    forms.alert("Shared parameter file not found:\n{}".format(sp_path),
                exitscript=True)

output = script.get_output()
output.print_md("**Base name:** {}".format(base_name))
output.print_md("**Levels:** {} → {}".format(start_level.Name, end_level.Name))
output.print_md("**Shared parameter file:** {}".format(sp_path))

# ---------------------------------------------------------------------------
# STEP 5 – Ensure shared parameter is bound to Assembly Instance category
# ---------------------------------------------------------------------------
def get_or_create_shared_param(doc, app, sp_file_path):
    """
    Finds 'Total Wall Volume' in the shared parameter file and ensures
    it is bound to the Assembly Instance category as an instance parameter.
    Returns the Definition if successful, None otherwise.
    """
    # Point Revit at the shared parameter file
    orig_sp_file = None
    try:
        orig_sp_file = app.SharedParametersFilename
    except Exception:
        pass

    app.SharedParametersFilename = sp_file_path
    sp_file = app.OpenSharedParameterFile()

    if sp_file is None:
        output.print_md("  ✗ Could not open shared parameter file.")
        return None

    # Find or create the group
    sp_group = None
    for g in sp_file.Groups:
        if g.Name == SP_GROUP_NAME:
            sp_group = g
            break
    if sp_group is None:
        sp_group = sp_file.Groups.Create(SP_GROUP_NAME)

    # Find or create the definition
    ext_def = None
    for d in sp_group.Definitions:
        if d.Name == PARAM_NAME:
            ext_def = d
            break

    if ext_def is None:
        # Create new definition — volume = Double
        def_opts = DB.ExternalDefinitionCreationOptions(
            PARAM_NAME, DB.SpecTypeId.Volume)
        def_opts.UserModifiable = True
        ext_def = sp_group.Definitions.Create(def_opts)
        output.print_md("  Created shared parameter definition: **{}**".format(
            PARAM_NAME))
    else:
        output.print_md("  Found existing shared parameter: **{}**".format(
            PARAM_NAME))

    # Check if already bound to Assembly Instance
    asm_cat = doc.Settings.Categories.get_Item(
        DB.BuiltInCategory.OST_Assemblies)
    cat_set = DB.CategorySet()
    cat_set.Insert(asm_cat)

    binding = DB.InstanceBinding(cat_set)
    existing_map = doc.ParameterBindings

    # Walk existing bindings to see if already bound
    it = existing_map.ForwardIterator()
    already_bound = False
    while it.MoveNext():
        try:
            if it.Key.Name == PARAM_NAME:
                already_bound = True
                break
        except Exception:
            pass

    if not already_bound:
        with revit.Transaction("Bind Shared Parameter"):
            doc.ParameterBindings.Insert(ext_def, binding)
        output.print_md("  Bound **{}** to Assembly Instance category.".format(
            PARAM_NAME))
    else:
        output.print_md("  Parameter already bound to Assembly Instance.")

    # Restore original shared parameter file
    if orig_sp_file:
        try:
            app.SharedParametersFilename = orig_sp_file
        except Exception:
            pass

    return ext_def

output.print_md("\n**Setting up shared parameter...**")
ext_def = get_or_create_shared_param(doc, app, sp_path)
if ext_def is None:
    forms.alert("Failed to set up shared parameter. Aborting.", exitscript=True)

# ---------------------------------------------------------------------------
# STEP 6 – Helper functions
# ---------------------------------------------------------------------------
def is_structural(wall):
    p = wall.get_Parameter(DB.BuiltInParameter.WALL_STRUCTURAL_SIGNIFICANT)
    if p and p.AsInteger() == 1:
        return True
    p2 = wall.get_Parameter(DB.BuiltInParameter.WALL_STRUCTURAL_USAGE_PARAM)
    if p2 and p2.AsInteger() != 0:
        return True
    return False

def wall_volume_cf(wall):
    """Return wall volume in cubic feet (Revit internal units are cubic feet)."""
    p = wall.get_Parameter(DB.BuiltInParameter.HOST_VOLUME_COMPUTED)
    if p:
        return p.AsDouble()
    return 0.0

# ---------------------------------------------------------------------------
# STEP 7 – Collect all structural walls once
# ---------------------------------------------------------------------------
all_walls = list(
    DB.FilteredElementCollector(doc).OfClass(DB.Wall).ToElements()
)

# ---------------------------------------------------------------------------
# STEP 8 – Check for existing assembly names
# ---------------------------------------------------------------------------
existing_assembly_names = set()
for ai in (DB.FilteredElementCollector(doc)
           .OfClass(DB.AssemblyInstance).ToElements()):
    try:
        existing_assembly_names.add(ai.AssemblyTypeName)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# STEP 9 – Process each level
# ---------------------------------------------------------------------------
total_assemblies = 0
total_skipped    = 0
total_no_walls   = 0

for level in target_levels:
    output.print_md("\n---\n**Processing level: {}**".format(level.Name))

    level_walls = []
    for wall in all_walls:
        base_param = wall.get_Parameter(DB.BuiltInParameter.WALL_BASE_CONSTRAINT)
        if base_param and base_param.AsElementId() == level.Id:
            if is_structural(wall):
                level_walls.append(wall)

    if not level_walls:
        output.print_md("  ⚠ No structural walls found on this level.")
        total_no_walls += 1
        continue

    output.print_md("  Structural walls found: **{}**".format(len(level_walls)))

    assembly_name = "{} - {}".format(base_name, level.Name)

    if assembly_name in existing_assembly_names:
        output.print_md(
            "  ⚠ Assembly '{}' already exists — skipping.".format(assembly_name))
        total_skipped += 1
        continue

    # Compute total volume before creating assembly
    total_vol_cf = sum(wall_volume_cf(w) for w in level_walls)
    output.print_md("  Total wall volume: **{:.3f} CF**".format(total_vol_cf))

    # Filter out walls already in an assembly
    free_walls = []
    for w in level_walls:
        asm_id = w.get_Parameter(DB.BuiltInParameter.ELEM_ASSEMBLY_CODE_PARAM)
        # AssemblyInstanceId — if the wall is already in an assembly this will be valid
        if DB.AssemblyInstance.GetAssemblyInstanceId(doc, w.Id) == DB.ElementId.InvalidElementId:
            free_walls.append(w)
        else:
            output.print_md("  ⚠ Wall id {} already in an assembly — skipping.".format(
                w.Id.Value))

    if not free_walls:
        output.print_md("  ⚠ All walls on this level are already in assemblies.")
        total_skipped += 1
        continue

    if len(free_walls) != len(level_walls):
        output.print_md("  Using {} of {} walls (others already in assemblies).".format(
            len(free_walls), len(level_walls)))

    wall_ids    = List[DB.ElementId]([w.Id for w in free_walls])
    category_id = free_walls[0].Category.Id

    try:
        # Transaction 1: create assembly
        with revit.Transaction("Create Assembly - {}".format(level.Name)):
            assembly = DB.AssemblyInstance.Create(doc, wall_ids, category_id)

        # Transaction 2: name + write volume
        with revit.Transaction("Name Assembly + Write Volume - {}".format(
                level.Name)):
            doc.Regenerate()
            assembly.AssemblyTypeName = assembly_name

            # Write volume to shared parameter
            vol_param = assembly.LookupParameter(PARAM_NAME)

            if vol_param is None:
                output.print_md("  ⚠ LookupParameter returned None. Scanning all params...")
                for p in assembly.Parameters:
                    try:
                        pname = p.Definition.Name if p.Definition else "?"
                        output.print_md("    param: **{}** | readOnly: {}".format(
                            pname, p.IsReadOnly))
                        if pname == PARAM_NAME:
                            vol_param = p
                    except Exception:
                        pass

            if vol_param and not vol_param.IsReadOnly:
                vol_param.Set(total_vol_cf)
                output.print_md(
                    "  ✓ Volume written to '{}': **{:.3f} CF**".format(
                        PARAM_NAME, total_vol_cf))
            elif vol_param and vol_param.IsReadOnly:
                output.print_md("  ⚠ Parameter '{}' is read-only.".format(PARAM_NAME))
            else:
                output.print_md("  ✗ Parameter '{}' not found on assembly.".format(
                    PARAM_NAME))

        existing_assembly_names.add(assembly_name)
        output.print_md("  ✓ Assembly created: **{}**".format(assembly_name))
        total_assemblies += 1

    except Exception as e:
        output.print_md("  ✗ Error on {}: {}".format(level.Name, e))

# ---------------------------------------------------------------------------
# STEP 10 – Summary
# ---------------------------------------------------------------------------
output.print_md(
    "\n---\n**Summary**\n"
    "- Levels processed: {}\n"
    "- Assemblies created: {}\n"
    "- Levels skipped (already exists): {}\n"
    "- Levels with no structural walls: {}".format(
        len(target_levels), total_assemblies,
        total_skipped, total_no_walls
    )
)
