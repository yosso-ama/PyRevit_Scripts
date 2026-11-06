# -*- coding: utf-8 -*-
__title__ = "Walls\nto Parts"
"""
Convert Structural Walls to Parts by Level
-------------------------------------------
User selects a start level and end level.
For each level, script:
  1. Joins all structural walls together (so they become one part)
  2. Converts the joined walls to a single Part
Skips walls already divided into parts and reports results.
"""

from pyrevit import revit, DB, forms, script
from System.Collections.Generic import List

doc   = revit.doc
uidoc = revit.uidoc

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

output = script.get_output()
output.print_md("**Start level:** {}  →  **End level:** {}".format(
    start_level.Name, end_level.Name))
output.print_md("**Levels to process:** {}".format(
    ", ".join(l.Name for l in target_levels)))

# ---------------------------------------------------------------------------
# STEP 3 – Helper: is wall structural?
# ---------------------------------------------------------------------------
def is_structural(wall):
    p = wall.get_Parameter(DB.BuiltInParameter.WALL_STRUCTURAL_SIGNIFICANT)
    if p and p.AsInteger() == 1:
        return True
    p2 = wall.get_Parameter(DB.BuiltInParameter.WALL_STRUCTURAL_USAGE_PARAM)
    if p2 and p2.AsInteger() != 0:
        return True
    return False

# ---------------------------------------------------------------------------
# STEP 4 – Collect all structural walls once
# ---------------------------------------------------------------------------
all_walls = list(
    DB.FilteredElementCollector(doc)
    .OfClass(DB.Wall)
    .ToElements()
)

# ---------------------------------------------------------------------------
# STEP 5 – Process each level
# ---------------------------------------------------------------------------
total_joined    = 0
total_converted = 0
total_skipped   = 0
total_no_walls  = 0

for level in target_levels:
    output.print_md("\n---\n**Processing level: {}**".format(level.Name))

    # Collect structural walls on this level
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

    # Separate into eligible and already-parted
    eligible = []
    skipped  = []
    for wall in level_walls:
        wall_ids = List[DB.ElementId]([wall.Id])
        if DB.PartUtils.AreElementsValidForCreateParts(doc, wall_ids):
            eligible.append(wall)
        else:
            skipped.append(wall)

    if skipped:
        output.print_md("  ⚠ Already divided (skipped): **{}** wall(s)".format(
            len(skipped)))
        for w in skipped:
            output.print_md("    - Wall id {}  type: {}".format(
                w.Id.Value, w.WallType.Name))
        total_skipped += len(skipped)

    if not eligible:
        output.print_md("  No eligible walls to convert on this level.")
        continue

    # ------------------------------------------------------------------
    # Join all eligible walls together so they merge into one part
    # ------------------------------------------------------------------
    joins_made = 0
    join_errors = 0

    if len(eligible) > 1:
        with revit.Transaction("Join Walls - {}".format(level.Name)):
            for i in range(len(eligible)):
                for j in range(i + 1, len(eligible)):
                    w1 = eligible[i]
                    w2 = eligible[j]
                    try:
                        # Only join if not already joined
                        if not DB.JoinGeometryUtils.AreElementsJoined(doc, w1, w2):
                            DB.JoinGeometryUtils.JoinGeometry(doc, w1, w2)
                            joins_made += 1
                    except Exception:
                        # Walls that don't touch can't be joined — not an error
                        join_errors += 1

        output.print_md("  Joins made: **{}**  (skipped non-touching: {})".format(
            joins_made, join_errors))
        total_joined += joins_made
    else:
        output.print_md("  Single wall on level — no joining needed.")

    # ------------------------------------------------------------------
    # Convert all eligible walls to parts
    # ------------------------------------------------------------------
    eligible_ids = List[DB.ElementId]([w.Id for w in eligible])

    try:
        with revit.Transaction("Convert Walls to Parts - {}".format(level.Name)):
            DB.PartUtils.CreateParts(doc, eligible_ids)
        output.print_md("  ✓ Converted **{}** wall(s) to Parts.".format(
            len(eligible)))
        total_converted += len(eligible)
    except Exception as e:
        output.print_md("  ✗ Error converting walls on {}: {}".format(
            level.Name, e))

# ---------------------------------------------------------------------------
# STEP 6 – Summary
# ---------------------------------------------------------------------------
output.print_md(
    "\n---\n**Summary**\n"
    "- Levels processed: {}\n"
    "- Wall joins made: {}\n"
    "- Walls converted to Parts: {}\n"
    "- Walls skipped (already parted): {}\n"
    "- Levels with no structural walls: {}".format(
        len(target_levels), total_joined,
        total_converted, total_skipped, total_no_walls
    )
)
