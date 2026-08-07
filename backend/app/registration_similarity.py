from __future__ import annotations

import re


OCR_CONFUSABLE_GROUPS = (
    frozenset("0OQ"),
    frozenset("1IL"),
    frozenset("2Z"),
    frozenset("5S"),
    frozenset("6G"),
    frozenset("8B"),
)


def normalize_registration(value: str | None) -> str:
    """Normalize registration text without guessing missing characters."""
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def registration_similarity(observed: str | None, candidate: str | None) -> float:
    """Return a 0..1 OCR-aware Damerau-Levenshtein similarity."""
    left = normalize_registration(observed)
    right = normalize_registration(candidate)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0

    rows = len(left) + 1
    columns = len(right) + 1
    distance = [[0.0] * columns for _ in range(rows)]
    for index in range(rows):
        distance[index][0] = float(index)
    for index in range(columns):
        distance[0][index] = float(index)

    for row in range(1, rows):
        for column in range(1, columns):
            substitution = _substitution_cost(left[row - 1], right[column - 1])
            distance[row][column] = min(
                distance[row - 1][column] + 1.0,
                distance[row][column - 1] + 1.0,
                distance[row - 1][column - 1] + substitution,
            )
            if (
                row > 1
                and column > 1
                and left[row - 1] == right[column - 2]
                and left[row - 2] == right[column - 1]
            ):
                distance[row][column] = min(
                    distance[row][column], distance[row - 2][column - 2] + 0.5
                )

    similarity = 1.0 - distance[-1][-1] / max(len(left), len(right))
    return round(max(0.0, min(1.0, similarity)), 4)


def _substitution_cost(left: str, right: str) -> float:
    if left == right:
        return 0.0
    if any(left in group and right in group for group in OCR_CONFUSABLE_GROUPS):
        return 0.35
    return 1.0
