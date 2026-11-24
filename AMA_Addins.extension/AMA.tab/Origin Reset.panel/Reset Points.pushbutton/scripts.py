# -*- coding: utf-8 -*-

from pyrevit import revit, DB, forms

doc = revit.doc
view = revit.active_view


def get_origin_elements(doc):
    """Return Project Base Point, Survey Point, and Internal Origin."""

    elements = []

    # Project Base Point
    try:
        pbp = DB.BasePoint.GetProjectBasePoint(doc)
        if pbp:
            elements.append(pbp)
    except:
        pass

    # Survey Point
    try:
        sp = DB.BasePoint.GetSurveyPoint(doc)
        if sp:
            elements.append(sp)
    except:
        pass

    # Internal Origin
    try:
        internal_origins = (
            DB.FilteredElementCollector(doc)
            .OfClass(DB.InternalOrigin)
            .ToElements()
        )

        for item in internal_origins:
            elements.append(item)

    except:
        pass

    return elements


def get_crop_extents(elements, view):
    """Get XY extents of coordinate points in crop-box coordinates."""

    crop = view.CropBox
    inv = crop.Transform.Inverse

    min_x = float("inf")
    min_y = float("inf")
    max_x = float("-inf")
    max_y = float("-inf")

    found = False

    for elem in elements:

        try:
            bbox = elem.get_BoundingBox(None)

            if bbox is None:
                continue

            for x in (bbox.Min.X, bbox.Max.X):
                for y in (bbox.Min.Y, bbox.Max.Y):
                    for z in (bbox.Min.Z, bbox.Max.Z):

                        pt = DB.XYZ(x, y, z)

                        # Element bounding box -> model coordinates
                        model_pt = bbox.Transform.OfPoint(pt)

                        # Model -> crop coordinates
                        crop_pt = inv.OfPoint(model_pt)

                        min_x = min(min_x, crop_pt.X)
                        min_y = min(min_y, crop_pt.Y)

                        max_x = max(max_x, crop_pt.X)
                        max_y = max(max_y, crop_pt.Y)

                        found = True

        except:
            pass

    if not found:
        return None

    return min_x, min_y, max_x, max_y


origin_elements = get_origin_elements(doc)

if not origin_elements:
    forms.alert(
        "Could not locate the Revit coordinate points.",
        exitscript=True
    )


# Existing crop
crop = view.CropBox

crop_min = crop.Min
crop_max = crop.Max

origin_extents = get_crop_extents(origin_elements, view)

if origin_extents is None:
    forms.alert(
        "Could not determine coordinate point locations.",
        exitscript=True
    )

ox1, oy1, ox2, oy2 = origin_extents


# ------------------------------------------------------------
# Expand existing crop enough to include coordinate points
# ------------------------------------------------------------

PADDING = 10.0     # feet

new_min_x = min(crop_min.X, ox1 - PADDING)
new_min_y = min(crop_min.Y, oy1 - PADDING)

new_max_x = max(crop_max.X, ox2 + PADDING)
new_max_y = max(crop_max.Y, oy2 + PADDING)


with revit.Transaction("Show Coordinate Points"):

    new_crop = DB.BoundingBoxXYZ()

    new_crop.Transform = crop.Transform

    new_crop.Min = DB.XYZ(
        new_min_x,
        new_min_y,
        crop_min.Z
    )

    new_crop.Max = DB.XYZ(
        new_max_x,
        new_max_y,
        crop_max.Z
    )

    view.CropBox = new_crop
    view.CropBoxActive = True
    view.CropBoxVisible = True


forms.alert(
    "Crop expanded to include the Project Base Point, "
    "Survey Point, and Internal Origin."
)