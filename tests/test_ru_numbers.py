from __future__ import annotations

import pytest

from app.media.ru_numbers import cardinal, normalize_numbers


@pytest.mark.parametrize(
    "value,expected",
    [
        (0, "ноль"),
        (2, "два"),
        (21, "двадцать один"),
        (100, "сто"),
        (123, "сто двадцать три"),
        (1000, "одна тысяча"),
        (2024, "две тысячи двадцать четыре"),
        (21000, "двадцать одна тысяча"),
        (1_000_000, "один миллион"),
        (2_500_000, "два миллиона пятьсот тысяч"),
        (-5, "минус пять"),
    ],
)
def test_cardinal(value, expected):
    assert cardinal(value) == expected


def test_normalize_numbers_spells_out_integers_and_percent():
    assert normalize_numbers("В 2024 году доход упал на 15%.") == (
        "В две тысячи двадцать четыре году доход упал на пятнадцать процентов."
    )
    assert normalize_numbers("Дом 42.") == "Дом сорок два."


def test_normalize_numbers_leaves_decimals_phones_and_long_ids_alone():
    assert normalize_numbers("Цена 3.14 и 1,5.") == "Цена 3.14 и 1,5."
    assert normalize_numbers("Позвони +79161234567.") == "Позвони +79161234567."
    assert normalize_numbers("Билет 4012888812345678.") == "Билет 4012888812345678."
