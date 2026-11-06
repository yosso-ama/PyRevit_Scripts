"""Sync the 2x8 sill plate X's when a section view is opened."""
import sill_x

try:
    args = __eventargs__
    doc, view = args.Document, args.CurrentActiveView
    if doc is not None and not doc.IsReadOnly and not doc.IsFamilyDocument and sill_x.is_section(view):
        sill_x.sync(doc, [view], 'Auto Sync Sill X')
except Exception:
    pass
