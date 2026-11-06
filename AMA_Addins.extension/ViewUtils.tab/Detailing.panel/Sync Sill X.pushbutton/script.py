"""Add, move or remove the 2x8 sill plate X in every section that cuts
FOUNDATION WALLS (NEW)."""
from pyrevit import revit, forms
import sill_x

result = sill_x.sync(revit.doc)
if result is None:
    forms.alert('Missing wall type "{}" or detail type "{} : {}".'.format(
        sill_x.WALL_TYPE, sill_x.DETAIL_FAMILY, sill_x.DETAIL_TYPE))
elif not result:
    forms.alert('Sill X\'s are already up to date in every section.')
else:
    lines = ['{}: {}'.format(name, ', '.join('{} {}'.format(n, k) for k, n in sorted(c.items())))
             for name, c in sorted(result.items())]
    forms.alert('Sill X\'s updated:\n\n' + '\n'.join(lines))
