"""Domain errors for V3 operation-admission transactions."""


class OperationAdmissionStoreError(RuntimeError):
    """The V3 admission store is incomplete, unsafe, or inconsistent."""


class OperationAdmissionIdempotencyConflictV3(OperationAdmissionStoreError):
    """An idempotency key was reused with different exact bytes."""


class OperationAdmissionAttemptConflictV3(OperationAdmissionStoreError):
    """An attempt identity is already owned by another V3 admission."""


class OperationAdmissionChildConflictV3(OperationAdmissionStoreError):
    """An intended child is already owned by another V3 admission."""
