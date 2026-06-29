"""Тесты нормализации единиц измерения."""

from packages.recipes_core.units import ALLOWED_UNITS, normalize_unit


class TestNormalizeUnit:

    def test_canonical_unit_unchanged(self):
        """Каноническое значение возвращается as-is."""
        for unit in ALLOWED_UNITS:
            if unit:
                assert normalize_unit(unit) == unit

    def test_none_returns_none(self):
        assert normalize_unit(None) is None

    def test_empty_string_returns_none(self):
        assert normalize_unit("") is None

    def test_alias_gr(self):
        assert normalize_unit("гр") == "г"

    def test_alias_gramm(self):
        assert normalize_unit("грамм") == "г"

    def test_alias_grammatov(self):
        assert normalize_unit("граммов") == "г"

    def test_alias_kilogramm(self):
        assert normalize_unit("килограмм") == "кг"

    def test_alias_millilitr(self):
        assert normalize_unit("миллилитр") == "мл"

    def test_alias_litr(self):
        assert normalize_unit("литр") == "л"

    def test_alias_stolovaya_lozhka(self):
        assert normalize_unit("столовая ложка") == "ст.л."

    def test_alias_chajnaya_lozhka(self):
        assert normalize_unit("чайная ложка") == "ч.л."

    def test_alias_shtuka(self):
        assert normalize_unit("штука") == "шт"

    def test_alias_shtuki(self):
        assert normalize_unit("штуки") == "шт"

    def test_alias_shtuk(self):
        assert normalize_unit("штук") == "шт"

    def test_whitespace_stripped(self):
        """Пробелы по краям обрезаются."""
        assert normalize_unit("  г  ") == "г"

    def test_unknown_unit_returned_as_is(self):
        """Неизвестная единица возвращается без изменений (без потери данных)."""
        assert normalize_unit("чашка") == "чашка"
        assert normalize_unit("горсть") == "горсть"

    def test_case_sensitive_aliases(self):
        """Алиасы регистрозависимы — canonical значения не трогаем."""
        assert normalize_unit("Г") == "Г"  # не алиас, возвращается as-is


class TestAllowedUnits:

    def test_not_empty(self):
        assert len(ALLOWED_UNITS) > 0

    def test_no_duplicates(self):
        assert len(ALLOWED_UNITS) == len(set(ALLOWED_UNITS))

    def test_contains_basic_units(self):
        for unit in ["г", "кг", "мл", "л", "шт", "ст.л.", "ч.л."]:
            assert unit in ALLOWED_UNITS
