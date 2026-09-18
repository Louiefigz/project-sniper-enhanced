"""Public errors for prospective unit-enrollment persistence."""


class UnitEnrollmentStoreError(RuntimeError):
    """The enrollment store is incomplete, unsafe, or inconsistent."""


class UnitEnrollmentKeyConflictV1(UnitEnrollmentStoreError):
    """An enrollment key was reused with different exact identity."""


class UnitEnrollmentUnitConflictV1(UnitEnrollmentStoreError):
    """A unit ID is already owned by another enrollment key."""
