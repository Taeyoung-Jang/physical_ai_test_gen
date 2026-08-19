"""Non-invasive bridges for candidate records produced by legacy pipelines."""

from .legacy_afs import LegacyAFSImportMethod
from .legacy_lam_guided import LegacyLAMGuidedImportMethod

__all__ = ["LegacyAFSImportMethod", "LegacyLAMGuidedImportMethod"]
