# -*- coding: utf-8 -*-
"""Create the safe room model from VAULT_STRUCTURAL.rte (runs safe_room.py)."""
__title__ = "Create\nSafe Room"
__context__ = "zero-doc"   # available even when no model is open

SCRIPT = r"D:\repos\claude-skills\revit-safe-room\safe_room.py"

# run with __file__ pointing at the real script so it finds the template next to it
exec(open(SCRIPT).read(), {"__file__": SCRIPT, "__revit__": __revit__, "__name__": "__main__"})
