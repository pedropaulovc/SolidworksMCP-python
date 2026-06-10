"""Grouped SolidWorks mixins for the PyWin32 adapter."""

from .features import SolidWorksFeaturesMixin
from .io import SolidWorksIOMixin
from .manufacturing import SolidWorksManufacturingMixin
from .measure import SolidWorksMeasureMixin
from .parametrics import SolidWorksParametricsMixin
from .reference_geometry import SolidWorksReferenceGeometryMixin
from .selection import SolidWorksSelectionMixin
from .sketch import SolidWorksSketchMixin

__all__ = [
    "SolidWorksFeaturesMixin",
    "SolidWorksIOMixin",
    "SolidWorksManufacturingMixin",
    "SolidWorksMeasureMixin",
    "SolidWorksParametricsMixin",
    "SolidWorksReferenceGeometryMixin",
    "SolidWorksSelectionMixin",
    "SolidWorksSketchMixin",
]
