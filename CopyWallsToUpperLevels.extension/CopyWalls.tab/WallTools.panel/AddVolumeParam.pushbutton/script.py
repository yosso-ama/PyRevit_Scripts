# -*- coding: utf-8 -*-
__title__ = "Add Volume\nParam"
"""
Add Total Wall Volume Shared Parameter
---------------------------------------
Adds the "Total Wall Volume" shared parameter to the Assembly Instance
category from the AMA Civil shared parameter file.
"""

import os
from pyrevit import revit, DB, forms, script

doc = revit.doc
app = doc.Application

PARAM_NAME    = "Total Wall Volume"
SP_GROUP_NAME = "Wall Assembly Parameters"
DEFAULT_SP    = r"Y:\CIVIL_CAD\REVIT_FILES\PARAMETERS\AMA_CIVIL_SHARED_PARAMS.txt"

# ---------------------------------------------------------------------------
# STEP 1 – Confirm / override shared parameter file path
# ---------------------------------------------------------------------------
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
output.print_md("**Shared parameter file:** {}".format(sp_path))

# ---------------------------------------------------------------------------
# STEP 2 – Open shared parameter file and find/create definition
# ---------------------------------------------------------------------------
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
    output.print_md("Created parameter group: **{}**".format(SP_GROUP_NAME))

# Find or create definition
ext_def = None
for d in sp_group.Definitions:
    if d.Name == PARAM_NAME:
        ext_def = d
        break

if ext_def is None:
    def_opts = DB.ExternalDefinitionCreationOptions(
        PARAM_NAME, DB.SpecTypeId.Volume)
    def_opts.UserModifiable = True
    ext_def = sp_group.Definitions.Create(def_opts)
    output.print_md("Created parameter definition: **{}**".format(PARAM_NAME))
else:
    output.print_md("Found existing parameter definition: **{}**".format(PARAM_NAME))

# ---------------------------------------------------------------------------
# STEP 3 – Check if already bound
# ---------------------------------------------------------------------------
it = doc.ParameterBindings.ForwardIterator()
already_bound = False
while it.MoveNext():
    try:
        if it.Key.Name == PARAM_NAME:
            already_bound = True
            break
    except Exception:
        pass

if already_bound:
    output.print_md("⚠ **{}** is already bound to Assembly Instance — nothing to do.".format(
        PARAM_NAME))
else:
    # ---------------------------------------------------------------------------
    # STEP 4 – Bind to Assembly Instance category
    # ---------------------------------------------------------------------------
    asm_cat = doc.Settings.Categories.get_Item(DB.BuiltInCategory.OST_Assemblies)
    cat_set = DB.CategorySet()
    cat_set.Insert(asm_cat)
    binding = DB.InstanceBinding(cat_set)

    with revit.Transaction("Add Shared Parameter - {}".format(PARAM_NAME)):
        success = doc.ParameterBindings.Insert(ext_def, binding)

    if success:
        output.print_md("✓ **{}** successfully bound to Assembly Instance category.".format(
            PARAM_NAME))
    else:
        output.print_md("✗ Binding failed — parameter may already exist under a different binding.")

# ---------------------------------------------------------------------------
# Restore original shared parameter file
# ---------------------------------------------------------------------------
if orig_sp:
    try:
        app.SharedParametersFilename = orig_sp
    except Exception:
        pass

output.print_md("\n**Done.**")
