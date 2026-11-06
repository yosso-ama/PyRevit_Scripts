walls = DB.FilteredElementCollector(doc).OfClass(DB.Wall).WhereElementIsNotElementType()
result = {"wall_count": walls.GetElementCount()}