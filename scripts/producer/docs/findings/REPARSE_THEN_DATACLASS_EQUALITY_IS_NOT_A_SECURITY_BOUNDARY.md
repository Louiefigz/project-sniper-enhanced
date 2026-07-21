# Reparse, then compare exact types

## Finding

Reparsing canonical bytes is not enough if the validator then compares the
parsed dataclass with a caller-constructed dataclass using normal `==`.
Python equality can dispatch to a field object's custom `__eq__`, allowing a
malicious leaf to claim that it equals the reparsed string.

The adversarial case affected multiple new headless wire boundaries, including
quality-pass input, approved-parent cards, generation verification, and the
materialized generation store. A receipt-focused red team found the first
instance; a repository-wide follow-up found the same pattern elsewhere.

```python
class AlwaysEqual:
    def __eq__(self, _other: object) -> bool:
        return True

forged = dataclasses.replace(parsed, request_digest=AlwaysEqual())
```

The safe comparison recursively requires the exact same concrete type before
comparing primitive values:

```python
def same_wire_value(actual: object, expected: object) -> bool:
    if type(actual) is not type(expected):
        return False
    # Recurse through dataclasses and tuples; compare only exact primitive types.
```

Leaf validators should likewise use `type(value) is str` rather than
`isinstance(value, str)` when a subclass has no legitimate wire meaning.

## Result

The shared exact-type comparator and stricter leaf checks now protect the
reparsed headless contracts. The focused regression set passed 59 tests and
109 subtests after the first hardening pass, including hostile string
subclasses and hostile direct dataclass construction.

## When not to use this approach

Do not replace ordinary equality everywhere. Business objects that deliberately
support compatible subclasses, numeric coercion, approximate measurement, or
custom value semantics should keep their domain comparison. Exact-type
recursive comparison is appropriate at a closed wire-authority boundary where
canonical JSON has already defined the only valid runtime types.
