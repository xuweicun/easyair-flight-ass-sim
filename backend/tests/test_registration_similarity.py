from app.registration_similarity import normalize_registration, registration_similarity


def test_registration_normalization_removes_separators_and_case() -> None:
    assert normalize_registration(" b-533 ") == "B533"


def test_requested_registration_ranking() -> None:
    assert registration_similarity("b533", "b53b") > registration_similarity(
        "b533", "b524"
    )


def test_common_ocr_confusion_has_lower_cost_than_unrelated_character() -> None:
    assert registration_similarity("B-5833", "B-5B33") > registration_similarity(
        "B-5833", "B-5433"
    )


def test_adjacent_transposition_is_tolerated() -> None:
    assert registration_similarity("B-5363", "B-5633") > 0.8
