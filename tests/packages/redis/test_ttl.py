from packages.redis import ttl


class TestTTLValues:
    """Тесты значений TTL констант."""

    def test_all_ttl_are_integers(self) -> None:
        """Все TTL константы — целые числа (секунды)."""
        ttl_constants = [
            ttl.USER_EXISTS,
            ttl.RECIPE_COUNT_SHORT,
            ttl.RECIPE_COUNT_LONG,
            ttl.LOCK,
            ttl.USER_CATEGORIES,
            ttl.USER_RECIPES_IDS_AND_TITLES,
            ttl.PIPELINE_DRAFT,
            ttl.RECIPE_ACTION,
            ttl.WEBAPP_RECIPE_DRAFT,
        ]

        for value in ttl_constants:
            assert isinstance(value, int)
            assert value > 0

    def test_user_exists_is_7_days(self) -> None:
        """USER_EXISTS = 7 дней в секундах."""
        expected = 7 * 24 * 60 * 60
        assert ttl.USER_EXISTS == expected
        assert ttl.USER_EXISTS == 604800

    def test_recipe_count_short_is_15_seconds(self) -> None:
        """RECIPE_COUNT_SHORT = 15 секунд."""
        assert ttl.RECIPE_COUNT_SHORT == 15

    def test_recipe_count_long_is_24_hours(self) -> None:
        """RECIPE_COUNT_LONG = 24 часа в секундах."""
        expected = 24 * 60 * 60
        assert ttl.RECIPE_COUNT_LONG == expected
        assert ttl.RECIPE_COUNT_LONG == 86400

    def test_lock_is_10_seconds(self) -> None:
        """LOCK = 10 секунд."""
        assert ttl.LOCK == 10

    def test_user_categories_is_24_hours(self) -> None:
        """USER_CATEGORIES = 24 часа в секундах."""
        expected = 24 * 60 * 60
        assert ttl.USER_CATEGORIES == expected
        assert ttl.USER_CATEGORIES == 86400

    def test_user_recipes_ids_and_titles_is_10_minutes(self) -> None:
        """USER_RECIPES_IDS_AND_TITLES = 10 минут в секундах."""
        expected = 10 * 60
        assert ttl.USER_RECIPES_IDS_AND_TITLES == expected
        assert ttl.USER_RECIPES_IDS_AND_TITLES == 600

    def test_pipeline_draft_is_24_hours(self) -> None:
        """PIPELINE_DRAFT = 24 часа в секундах."""
        expected = 24 * 60 * 60
        assert ttl.PIPELINE_DRAFT == expected
        assert ttl.PIPELINE_DRAFT == 86400

    def test_recipe_action_is_30_minutes(self) -> None:
        """RECIPE_ACTION = 30 минут в секундах."""
        expected = 30 * 60
        assert ttl.RECIPE_ACTION == expected
        assert ttl.RECIPE_ACTION == 1800

    def test_webapp_recipe_draft_is_10_minutes(self) -> None:
        """WEBAPP_RECIPE_DRAFT = 10 минут в секундах."""
        expected = 10 * 60
        assert ttl.WEBAPP_RECIPE_DRAFT == expected
        assert ttl.WEBAPP_RECIPE_DRAFT == 600


class TestTTLRelationships:
    """Тесты соотношений между TTL."""

    def test_lock_is_shortest(self) -> None:
        """LOCK самый короткий TTL."""
        ttl_values = [
            ttl.USER_EXISTS,
            ttl.RECIPE_COUNT_SHORT,
            ttl.RECIPE_COUNT_LONG,
            ttl.LOCK,
            ttl.USER_CATEGORIES,
            ttl.USER_RECIPES_IDS_AND_TITLES,
            ttl.PIPELINE_DRAFT,
            ttl.RECIPE_ACTION,
            ttl.WEBAPP_RECIPE_DRAFT,
        ]

        assert ttl.LOCK == min(ttl_values)

    def test_user_exists_is_longest(self) -> None:
        """USER_EXISTS самый длинный TTL."""
        ttl_values = [
            ttl.USER_EXISTS,
            ttl.RECIPE_COUNT_SHORT,
            ttl.RECIPE_COUNT_LONG,
            ttl.LOCK,
            ttl.USER_CATEGORIES,
            ttl.USER_RECIPES_IDS_AND_TITLES,
            ttl.PIPELINE_DRAFT,
            ttl.RECIPE_ACTION,
            ttl.WEBAPP_RECIPE_DRAFT,
        ]

        assert ttl.USER_EXISTS == max(ttl_values)

    def test_recipe_count_short_less_than_long(self) -> None:
        """RECIPE_COUNT_SHORT < RECIPE_COUNT_LONG."""
        assert ttl.RECIPE_COUNT_SHORT < ttl.RECIPE_COUNT_LONG

    def test_webapp_draft_shorter_than_pipeline_draft(self) -> None:
        """WEBAPP_RECIPE_DRAFT < PIPELINE_DRAFT."""
        assert ttl.WEBAPP_RECIPE_DRAFT < ttl.PIPELINE_DRAFT

    def test_recipe_action_longer_than_webapp_draft(self) -> None:
        """RECIPE_ACTION > WEBAPP_RECIPE_DRAFT."""
        assert ttl.RECIPE_ACTION > ttl.WEBAPP_RECIPE_DRAFT


class TestTTLCategories:
    """Классификация TTL по назначению."""

    def test_short_ttl_values(self) -> None:
        """Короткие TTL (для частых обновлений)."""
        short_ttl = [
            ttl.LOCK,  # 10 сек
            ttl.RECIPE_COUNT_SHORT,  # 15 сек
            ttl.WEBAPP_RECIPE_DRAFT,  # 10 мин
            ttl.USER_RECIPES_IDS_AND_TITLES,  # 10 мин
        ]

        for value in short_ttl:
            assert value < 20 * 60  # Менее 20 минут

    def test_medium_ttl_values(self) -> None:
        """Средние TTL (30 минут)."""
        medium_ttl = [
            ttl.RECIPE_ACTION,  # 30 мин
        ]

        for value in medium_ttl:
            assert 20 * 60 <= value < 24 * 60 * 60

    def test_long_ttl_values(self) -> None:
        """Длинные TTL (24 часа)."""
        long_ttl = [
            ttl.USER_CATEGORIES,  # 24 часа
            ttl.RECIPE_COUNT_LONG,  # 24 часа
            ttl.PIPELINE_DRAFT,  # 24 часа
        ]

        for value in long_ttl:
            assert value == 24 * 60 * 60

    def test_extra_long_ttl_values(self) -> None:
        """Очень длинные TTL (7 дней)."""
        extra_long_ttl = [
            ttl.USER_EXISTS,  # 7 дней
        ]

        for value in extra_long_ttl:
            assert value > 24 * 60 * 60


class TestTTLReasonableness:
    """Тесты разумности значений TTL."""

    def test_lock_is_very_short(self) -> None:
        """Lock TTL должен быть очень коротким для предотвращения deadlock."""
        assert ttl.LOCK <= 30
        assert ttl.LOCK > 0

    def test_recipe_count_short_reasonable(self) -> None:
        """RECIPE_COUNT_SHORT разумен для частых проверок."""
        assert 10 <= ttl.RECIPE_COUNT_SHORT <= 30

    def test_no_ttl_is_negative_or_zero(self) -> None:
        """Ни один TTL не может быть отрицательным или нулевым."""
        ttl_constants = [
            ttl.USER_EXISTS,
            ttl.RECIPE_COUNT_SHORT,
            ttl.RECIPE_COUNT_LONG,
            ttl.LOCK,
            ttl.USER_CATEGORIES,
            ttl.USER_RECIPES_IDS_AND_TITLES,
            ttl.PIPELINE_DRAFT,
            ttl.RECIPE_ACTION,
            ttl.WEBAPP_RECIPE_DRAFT,
        ]

        for value in ttl_constants:
            assert value > 0

    def test_all_ttl_reasonable_upper_bound(self) -> None:
        """Все TTL < 30 дней (разумный верхний предел для кэша)."""
        max_reasonable_ttl = 30 * 24 * 60 * 60

        ttl_constants = [
            ttl.USER_EXISTS,
            ttl.RECIPE_COUNT_SHORT,
            ttl.RECIPE_COUNT_LONG,
            ttl.LOCK,
            ttl.USER_CATEGORIES,
            ttl.USER_RECIPES_IDS_AND_TITLES,
            ttl.PIPELINE_DRAFT,
            ttl.RECIPE_ACTION,
            ttl.WEBAPP_RECIPE_DRAFT,
        ]

        for value in ttl_constants:
            assert value <= max_reasonable_ttl


class TestTTLReadability:
    """Тесты читаемости и документированности значений."""

    def test_ttl_constants_are_descriptive_named(self) -> None:
        """TTL константы имеют описательные имена."""
        # Проверяем, что константы существуют и их имена понятны
        constants = {
            "USER_EXISTS": ttl.USER_EXISTS,
            "RECIPE_COUNT_SHORT": ttl.RECIPE_COUNT_SHORT,
            "RECIPE_COUNT_LONG": ttl.RECIPE_COUNT_LONG,
            "LOCK": ttl.LOCK,
            "USER_CATEGORIES": ttl.USER_CATEGORIES,
            "USER_RECIPES_IDS_AND_TITLES": ttl.USER_RECIPES_IDS_AND_TITLES,
            "PIPELINE_DRAFT": ttl.PIPELINE_DRAFT,
            "RECIPE_ACTION": ttl.RECIPE_ACTION,
            "WEBAPP_RECIPE_DRAFT": ttl.WEBAPP_RECIPE_DRAFT,
        }

        for name, value in constants.items():
            assert isinstance(name, str)
            assert len(name) > 0
            assert value > 0
