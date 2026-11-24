# -*- coding: utf-8 -*-

from pyrevit import revit, DB, forms


doc = revit.doc
view = revit.active_view

# ------------------------------------------------------------
# SETTINGS
# ------------------------------------------------------------

# Padding around model extents, in feet
CROP_PADDING = 10.0


# ------------------------------------------------------------
# FUNCTIONS
# ------------------------------------------------------------

def get_visible_model_elements(doc, view):
    """
    Return visible model elements in the active view.

    Excludes:
        - Element types
        - View-specific annotation
        - Non-model categories
        - Elements without a bounding box
    """

    elements = []

    collector = (
        DB.FilteredElementCollector(doc, view.Id)
        .WhereElementIsNotElementType()
    )

    for elem in collector:

        # Skip view-specific elements such as annotations
        if elem.ViewSpecific:
            continue

        category = elem.Category

        if category is None:
            continue

        # Only actual model categories
        if category.CategoryType != DB.CategoryType.Model:
            continue

        try:
            bbox = elem.get_BoundingBox(view)

            if bbox is None:
                continue

            elements.append(elem)

        except:
            continue

    return elements


def get_model_extents_in_crop_coordinates(elements, view):
    """
    Determine the model extents using the coordinate system
    of the existing crop box.

    This is important because CropBox Min/Max are expressed
    relative to the CropBox Transform.
    """

    crop_box = view.CropBox
    crop_transform = crop_box.Transform
    inverse_transform = crop_transform.Inverse

    min_x = float("inf")
    min_y = float("inf")

    max_x = float("-inf")
    max_y = float("-inf")

    found_bbox = False

    for elem in elements:

        try:
            bbox = elem.get_BoundingBox(view)

            if bbox is None:
                continue

            # BoundingBoxXYZ itself can have a transform.
            bbox_transform = bbox.Transform

            # Check all 8 corners.
            for x in (bbox.Min.X, bbox.Max.X):
                for y in (bbox.Min.Y, bbox.Max.Y):
                    for z in (bbox.Min.Z, bbox.Max.Z):

                        local_pt = DB.XYZ(x, y, z)

                        # Convert element bbox coordinates to model coordinates.
                        model_pt = bbox_transform.OfPoint(local_pt)

                        # Convert model coordinates into crop-box coordinates.
                        crop_pt = inverse_transform.OfPoint(model_pt)

                        min_x = min(min_x, crop_pt.X)
                        min_y = min(min_y, crop_pt.Y)

                        max_x = max(max_x, crop_pt.X)
                        max_y = max(max_y, crop_pt.Y)

                        found_bbox = True

        except:
            continue

    if not found_bbox:
        return None

    return min_x, min_y, max_x, max_y


def scope_box_is_assigned(view):
    """
    Returns True if the view crop is being controlled
    by a Scope Box.
    """

    try:
        param = view.get_Parameter(
            DB.BuiltInParameter.VIEWER_VOLUME_OF_INTEREST_CROP
        )

        if param is None:
            return False

        scope_box_id = param.AsElementId()

        return (
            scope_box_id is not None
            and scope_box_id != DB.ElementId.InvalidElementId
        )

    except:
        return False


# ------------------------------------------------------------
# VALIDATE VIEW
# ------------------------------------------------------------

allowed_view_types = [
    DB.ViewType.FloorPlan,
    DB.ViewType.CeilingPlan,
    DB.ViewType.EngineeringPlan,
    DB.ViewType.AreaPlan,
]

if view.ViewType not in allowed_view_types:
    forms.alert(
        "The active view must be a plan view.",
        title="Reset Crop",
        exitscript=True
    )


if view.IsTemplate:
    forms.alert(
        "The active view is a view template.",
        title="Reset Crop",
        exitscript=True
    )


# ------------------------------------------------------------
# CHECK SCOPE BOX
# ------------------------------------------------------------

if scope_box_is_assigned(view):

    forms.alert(
        "This view is controlled by a Scope Box.\n\n"
        "Set the view's Scope Box parameter to <None> "
        "before resetting the crop region.",
        title="Reset Crop",
        exitscript=True
    )


# ------------------------------------------------------------
# FIND MODEL EXTENTS
# ------------------------------------------------------------

elements = get_visible_model_elements(doc, view)

if not elements:
    forms.alert(
        "No visible model elements were found in this view.",
        title="Reset Crop",
        exitscript=True
    )


extents = get_model_extents_in_crop_coordinates(elements, view)

if extents is None:
    forms.alert(
        "Unable to determine the model extents.",
        title="Reset Crop",
        exitscript=True
    )


min_x, min_y, max_x, max_y = extents


# ------------------------------------------------------------
# ADD PADDING
# ------------------------------------------------------------

min_x -= CROP_PADDING
min_y -= CROP_PADDING

max_x += CROP_PADDING
max_y += CROP_PADDING


# ------------------------------------------------------------
# RESET CROP
# ------------------------------------------------------------

with revit.Transaction("Reset Plan Crop"):

    crop_box = view.CropBox

    # Preserve Z because Z does not define the visible plan crop.
    old_min = crop_box.Min
    old_max = crop_box.Max

    crop_box.Min = DB.XYZ(
        min_x,
        min_y,
        old_min.Z
    )

    crop_box.Max = DB.XYZ(
        max_x,
        max_y,
        old_max.Z
    )

    view.CropBox = crop_box

    view.CropBoxActive = True
    view.CropBoxVisible = True


forms.alert(
    "Crop region reset to visible model extents.",
    title="Reset Crop"
)