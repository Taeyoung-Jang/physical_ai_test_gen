"""Built-in baseline failure-discovery methods."""

from .manual_method import ManualMethod
from .random_method import RandomMethod
from .sobol_method import SobolMethod

__all__ = ["ManualMethod", "RandomMethod", "SobolMethod"]

