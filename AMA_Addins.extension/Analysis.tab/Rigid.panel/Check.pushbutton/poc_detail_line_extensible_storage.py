# -*- coding: utf-8 -*-
"""PROOF OF CONCEPT #2: store custom metadata on a detail line via
Extensible Storage.

Why this exists
---------------
POC #1 confirmed detail lines will NOT accept a project/shared parameter
(the Lines category has no checkbox in the parameter-binding dialog).
Extensible Storage attaches script-owned data straight to the element instead,
with no category binding. Tradeoff: the data is invisible in the Properties
palette and cannot be scheduled or tagged -- it is only reachable in code.

What it does
------------
Pick ONE detail line, write TEST_VALUE into an ExtensibleStorage entity on it,
read it straight back, and report PASSED / MISMATCH / ERROR. Run it twice on the
same line to confirm the value persists between runs (proves it is stored on the
element, not just in memory).

No UI setup required -- the schema is created in code on first run.
"""

import System
from System import Guid

from pyrevit import revit, DB, forms, script
from Autodesk.Revit.DB.ExtensibleStorage import (
    Schema, SchemaBuilder, AccessLevel)
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException

# ------------------------------------------------------------------ CONFIG ---
# Fixed GUID so the same schema is found on every run / machine. Generate your
# own for production (any unique GUID); keep it constant once chosen.
SCHEMA_GUID  = Guid("b7e3c2a4-1f6d-4c9a-9e2b-8a1d5f3c7e01")
SCHEMA_NAME  = "CORWallData"     # alphanumeric, no spaces
FIELD_NAME   = "WallMark"        # alphanumeric, no spaces
TEST_VALUE   = "shear-A1"        # text value to round-trip
# -----------------------------------------------------------------------------

doc    = revit.doc
uidoc  = revit.uidoc
output = script.get_output()


class _DetailLineFilter(ISelectionFilter):
    def AllowElement(self, element):
        return isinstance(element, DB.DetailLine)

    def AllowReference(self, reference, position):
        return False


def pick_one_detail_line():
    try:
        ref = uidoc.Selection.PickObject(
            ObjectType.Element, _DetailLineFilter(),
            "Pick ONE detail line to test Extensible Storage on.")
    except OperationCanceledException:
        return None
    return doc.GetElement(ref)


def get_or_create_schema():
    """Return the schema, building it once if it doesn't exist yet."""
    existing = Schema.Lookup(SCHEMA_GUID)
    if existing is not None:
        return existing
    sb = SchemaBuilder(SCHEMA_GUID)
    sb.SetSchemaName(SCHEMA_NAME)
    sb.SetReadAccessLevel(AccessLevel.Public)
    sb.SetWriteAccessLevel(AccessLevel.Public)
    sb.AddSimpleField(FIELD_NAME, System.String)   # text field, no units needed
    return sb.Finish()


def read_stored_value(el, schema):
    """Return the stored string, or None if nothing is stored yet."""
    ent = el.GetEntity(schema)
    if ent is None or not ent.IsValid():
        return None
    return ent.Get[System.String](FIELD_NAME)


def main():
    el = pick_one_detail_line()
    if el is None:
        forms.alert("No detail line picked.", title="Extensible Storage POC")
        return

    output.print_md("# Detail-line Extensible Storage POC")
    output.print_md("Element id: `%s`" % el.Id)

    try:
        schema = get_or_create_schema()
    except Exception as ex:
        output.print_md("## **ERROR building schema**\n\n`%s`" % ex)
        return

    before = read_stored_value(el, schema)
    output.print_md("- Value found before this run: `%s`"
                    % (before if before is not None else "<none stored yet>"))

    try:
        from Autodesk.Revit.DB.ExtensibleStorage import Entity
        with revit.Transaction("POC write ExtensibleStorage on detail line"):
            ent = Entity(schema)
            ent.Set[System.String](FIELD_NAME, TEST_VALUE)
            el.SetEntity(ent)
        after = read_stored_value(el, schema)
        ok = (after == TEST_VALUE)
        output.print_md(
            "## Round-trip test: **%s**\n\n"
            "- Schema: `%s`  field `%s`\n"
            "- Wrote: `%s`\n"
            "- Read back: `%s`"
            % ("PASSED" if ok else "MISMATCH",
               SCHEMA_NAME, FIELD_NAME, TEST_VALUE, after))
        output.print_md(
            "_Run this again on the same line: 'Value found before this run' "
            "should now read `%s`, proving it persists on the element._"
            % TEST_VALUE)
    except Exception as ex:
        output.print_md("## Round-trip test: **ERROR**\n\n`%s`" % ex)


if __name__ == "__main__":
    main()
