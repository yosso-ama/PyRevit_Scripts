# -*- coding: utf-8 -*-
__title__ = "Copy Walls\nUp"
"""
Copy Walls to Upper Levels
--------------------------
1. Creates Floor Plan views for all levels that don't already have one.
2. Prompts user to select a source level.
3. Copies all walls on that level to every level above it (walls only, no hosted elements).
"""

from pyrevit import revit, DB, forms, script
from System.Collections.Generic import List

doc    = revit.doc
uidoc  = revit.uidoc
output = script.get_output()

# ---------------------------------------------------------------------------
# STEP 1 – Collect all levels, sorted by elevation
# ---------------------------------------------------------------------------
all_levels = list(
    DB.FilteredElementCollector(doc)
    .OfClass(DB.Level)
    .ToElements()
)
all_levels = sorted(all_levels, key=lambda l: l.Elevation)

if not all_levels:
    forms.alert("No levels found in the model.", exitscript=True)

output.print_md("**Levels found:** " + ", ".join(l.Name for l in all_levels))

# ---------------------------------------------------------------------------
# STEP 2 – Create Floor Plan views for levels that don't already have one
# ---------------------------------------------------------------------------
# Find a Floor Plan view family type to use
floor_plan_vft = None
for vft in (
    DB.FilteredElementCollector(doc)
    .OfClass(DB.ViewFamilyType)
    .ToElements()
):
    if vft.ViewFamily == DB.ViewFamily.StructuralPlan:
        floor_plan_vft = vft
        break

if floor_plan_vft is None:
    forms.alert("No Floor Plan view family type found.", exitscript=True)

output.print_md("**View Family Type:** " + floor_plan_vft.get_Parameter(
    DB.BuiltInParameter.ALL_MODEL_TYPE_NAME).AsString())

# Build a set of level IDs that already have a floor plan view
# Guard against GenLevel being None (area plans, etc.)
existing_plan_level_ids = set()
for v in (
    DB.FilteredElementCollector(doc)
    .OfClass(DB.ViewPlan)
    .ToElements()
):
    try:
        if v.ViewType == DB.ViewType.EngineeringPlan and not v.IsTemplate:
            gen_level = v.GenLevel
            if gen_level is not None:
                existing_plan_level_ids.add(gen_level.Id)
    except Exception:
        pass

output.print_md(
    "**Levels already with a Floor Plan view:** {}".format(len(existing_plan_level_ids))
)

views_created = []
views_skipped = []

with revit.Transaction("Create Floor Plan Views"):
    for level in all_levels:
        if level.Id not in existing_plan_level_ids:
            try:
                new_view = DB.ViewPlan.Create(doc, floor_plan_vft.Id, level.Id)
                # Name must be unique — append level name; Revit may auto-suffix if duplicate
                try:
                    new_view.Name = level.Name
                except Exception as name_err:
                    output.print_md(
                        "  ⚠ Could not rename view for **{}**: {}".format(level.Name, name_err)
                    )
                views_created.append(level.Name)
            except Exception as create_err:
                output.print_md(
                    "  ✗ Failed to create view for **{}**: {}".format(level.Name, create_err)
                )
        else:
            views_skipped.append(level.Name)

if views_created:
    output.print_md("**Floor Plan views created:** " + ", ".join(views_created))
else:
    output.print_md("⚠ No new views were created.")

if views_skipped:
    output.print_md("**Skipped (already have a Floor Plan):** " + ", ".join(views_skipped))

# ---------------------------------------------------------------------------
# STEP 3 – User selects the source level
# ---------------------------------------------------------------------------
level_names = [l.Name for l in all_levels]
selected_name = forms.SelectFromList.show(
    level_names,
    title="Select Source Level",
    message="Select the level whose walls will be copied to all levels above:",
    multiselect=False,
)

if not selected_name:
    script.exit()

source_level = next(l for l in all_levels if l.Name == selected_name)
source_index = all_levels.index(source_level)
target_levels = all_levels[source_index + 1:]

if not target_levels:
    forms.alert("No levels exist above '{}'.".format(selected_name), exitscript=True)

output.print_md("**Source level:** {}".format(selected_name))
output.print_md(
    "**Target levels:** " + ", ".join(l.Name for l in target_levels)
)

# ---------------------------------------------------------------------------
# STEP 4 – Collect walls on the source level
# ---------------------------------------------------------------------------
source_walls = []
for wall in (
    DB.FilteredElementCollector(doc)
    .OfClass(DB.Wall)
    .ToElements()
):
    try:
        base_param = wall.get_Parameter(DB.BuiltInParameter.WALL_BASE_CONSTRAINT)
        if base_param and base_param.AsElementId() == source_level.Id:
            source_walls.append(wall)
    except Exception:
        pass

if not source_walls:
    forms.alert(
        "No walls found on level '{}'. Nothing to copy.".format(selected_name),
        exitscript=True,
    )

output.print_md("**Walls found on source level:** {}".format(len(source_walls)))

# Build a dict of wall Id -> unconnected height to carry over to copies
wall_height_map = {}
for w in source_walls:
    # Ensure top constraint is Unconnected so WALL_USER_HEIGHT_PARAM is valid
    top_type = w.get_Parameter(DB.BuiltInParameter.WALL_HEIGHT_TYPE)
    if top_type and top_type.AsElementId() == DB.ElementId.InvalidElementId:
        h_param = w.get_Parameter(DB.BuiltInParameter.WALL_USER_HEIGHT_PARAM)
        if h_param:
            wall_height_map[w.Id] = h_param.AsDouble()
    else:
        # Wall has a top constraint level — compute height from level elevations
        h_param = w.get_Parameter(DB.BuiltInParameter.WALL_USER_HEIGHT_PARAM)
        if h_param:
            wall_height_map[w.Id] = h_param.AsDouble()

wall_ids = List[DB.ElementId]([w.Id for w in source_walls])

# ---------------------------------------------------------------------------
# STEP 5 – Copy walls to each target level
# ---------------------------------------------------------------------------
source_elev  = source_level.Elevation
total_copied = 0

with revit.Transaction("Copy Walls to Upper Levels"):
    for target_level in target_levels:
        delta_z     = target_level.Elevation - source_elev
        translation = DB.XYZ(0, 0, delta_z)

        copied_ids = DB.ElementTransformUtils.CopyElements(
            doc,
            wall_ids,
            doc,
            DB.Transform.Identity,
            DB.CopyPasteOptions(),
        )

        DB.ElementTransformUtils.MoveElements(doc, copied_ids, translation)

        # copied_ids order matches wall_ids order
        source_id_list = [w.Id for w in source_walls]
        for i, eid in enumerate(copied_ids):
            wall = doc.GetElement(eid)
            if wall is None:
                continue

            # Re-pin base constraint to target level
            base_p = wall.get_Parameter(DB.BuiltInParameter.WALL_BASE_CONSTRAINT)
            if base_p:
                base_p.Set(target_level.Id)

            # Zero out base offset
            base_off = wall.get_Parameter(DB.BuiltInParameter.WALL_BASE_OFFSET)
            if base_off:
                base_off.Set(0.0)

            # Set top constraint to Unconnected
            top_p = wall.get_Parameter(DB.BuiltInParameter.WALL_HEIGHT_TYPE)
            if top_p:
                top_p.Set(DB.ElementId.InvalidElementId)

            # Apply the same unconnected height as the source wall
            src_id = source_id_list[i]
            if src_id in wall_height_map:
                h_param = wall.get_Parameter(DB.BuiltInParameter.WALL_USER_HEIGHT_PARAM)
                if h_param and not h_param.IsReadOnly:
                    h_param.Set(wall_height_map[src_id])

        count = len(list(copied_ids))
        total_copied += count
        output.print_md(
            "  ✓ Copied {} walls → **{}**".format(count, target_level.Name)
        )

output.print_md(
    "\n**Done.** {} wall instances copied across {} levels.".format(
        total_copied, len(target_levels)
    )
)
