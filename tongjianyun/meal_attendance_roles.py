"""Compatibility target for the existing after_migrate hook.

Teacher attendance is authorized by the scoped classroom/domain service, not by
granting access to a whole-school Daily Meal Confirmation. This intentionally
does not modify roles, DocPerm, User records or existing site customizations.
Standard Education permissions (including attendance read access) still apply.
"""


def install():
    """Idempotent, non-mutating compatibility hook; no permission elevation."""
    return None
