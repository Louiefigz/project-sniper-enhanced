"""Optional exact-sample/occurrence propagation for resolved caption words."""
from __future__ import annotations

from captions.caption_contract import CaptionContractError, WORD_ID_RE

_SAMPLE_KEYS = {"startSample", "endSampleExclusive"}
_IDENTITY_KEYS = {"sourceWordId", "occurrence"}


def validate_exact_word_timing(row: dict, index: int) -> None:
    """Validate optional dialogue timing without requiring it for legacy words."""
    sample_keys = _SAMPLE_KEYS & set(row)
    identity_keys = _IDENTITY_KEYS & set(row)
    if sample_keys and sample_keys != _SAMPLE_KEYS:
        raise CaptionContractError(
            f"resolved word {index} has incomplete exact sample timing")
    if identity_keys and identity_keys != _IDENTITY_KEYS:
        raise CaptionContractError(
            f"resolved word {index} has incomplete occurrence identity")
    if sample_keys:
        start, end = row["startSample"], row["endSampleExclusive"]
        if type(start) is not int or type(end) is not int \
                or start < 0 or end <= start:
            raise CaptionContractError(
                f"resolved word {index} has invalid exact samples")
    if identity_keys:
        source = row["sourceWordId"]
        occurrence = row["occurrence"]
        if not isinstance(source, str) or WORD_ID_RE.fullmatch(source) is None \
                or type(occurrence) is not int or occurrence <= 0:
            raise CaptionContractError(
                f"resolved word {index} has invalid occurrence identity")
    if bool(sample_keys) != bool(identity_keys):
        raise CaptionContractError(
            f"resolved word {index} must bind samples and occurrence together")


def _occurrences(words: list[dict]) -> list[dict]:
    return [{
        "sourceWordId": word["sourceWordId"],
        "occurrence": word["occurrence"],
    } for word in words]


def plain_token_exact_fields(word: dict) -> dict:
    """Return dialogue timing fields for one token, or nothing for legacy."""
    if "startSample" not in word:
        return {}
    return {
        "startSample": word["startSample"],
        "endSampleExclusive": word["endSampleExclusive"],
        "sourceWordOccurrences": _occurrences([word]),
    }


def _weighted_lengths(tokens: list[str], total: int) -> list[int]:
    if total < len(tokens):
        raise CaptionContractError(
            "correction has fewer samples than display tokens")
    weights = [max(1, len(token)) for token in tokens]
    available = total - len(tokens)
    weight_sum = sum(weights)
    extras = [available * weight // weight_sum for weight in weights]
    remaining = available - sum(extras)
    residuals = [
        (available * weight % weight_sum, -index)
        for index, weight in enumerate(weights)]
    for _, neg_index in sorted(residuals, reverse=True)[:remaining]:
        extras[-neg_index] += 1
    return [1 + extra for extra in extras]


def corrected_token_exact_fields(
    words: list[dict],
    tokens: list[str],
) -> list[dict]:
    """Split an exact corrected-word envelope across display tokens."""
    present = ["startSample" in word for word in words]
    if not any(present):
        return [{} for _ in tokens]
    if not all(present):
        raise CaptionContractError(
            "caption correction mixes exact and frame-derived word timing")
    start = words[0]["startSample"]
    end = words[-1]["endSampleExclusive"]
    lengths = _weighted_lengths(tokens, end - start)
    occurrences = _occurrences(words)
    result = []
    cursor = start
    for length in lengths:
        result.append({
            "startSample": cursor,
            "endSampleExclusive": cursor + length,
            "sourceWordOccurrences": occurrences,
        })
        cursor += length
    return result
