from packages.redis.keys import RedisKeys


class TestRedisKeysFormat:
    """Тесты формата Redis ключей."""

    def test_prefix_is_included(self) -> None:
        """Все ключи содержат PREFIX."""
        keys_to_test = [
            RedisKeys.user_exists(123),
            RedisKeys.recipe_count(456),
            RedisKeys.user_init_lock(789),
            RedisKeys.all_category(),
        ]

        for key in keys_to_test:
            assert key.startswith(RedisKeys.PREFIX)

    def test_key_format_uses_colons_as_delimiter(self) -> None:
        """Ключи используют двоеточие как разделитель."""
        key = RedisKeys.user_exists(123)
        assert ":" in key
        parts = key.split(":")
        assert len(parts) >= 2

    def test_all_keys_are_strings(self) -> None:
        """Все методы возвращают строки."""
        test_keys = [
            RedisKeys.user_exists(1),
            RedisKeys.recipe_count(1),
            RedisKeys.user_init_lock(1),
            RedisKeys.user_categories(1),
            RedisKeys.category_by_slug("test"),
            RedisKeys.slug_init_lock("test"),
            RedisKeys.all_category(),
            RedisKeys.catergory_lock(),
            RedisKeys.user_recipes_ids_and_titles(1, 2),
            RedisKeys.user_last_recipe_messages(1),
            RedisKeys.user_pipeline_draft(1, 2),
            RedisKeys.user_pipeline_ids(1),
            RedisKeys.user_recipe_action(1, "view"),
            RedisKeys.user_url_candidate_state(1, "sid123"),
            RedisKeys.user_progress_message(1),
            RedisKeys.user_webapp_recipe_draft(1, 2),
            RedisKeys.broadcast_worker_lock(),
        ]

        for key in test_keys:
            assert isinstance(key, str)
            assert len(key) > 0


class TestRedisKeysUserKeys:
    """Тесты для пользовательских ключей."""

    def test_user_exists_with_int_id(self) -> None:
        """user_exists() с целым числом."""
        key = RedisKeys.user_exists(123)
        assert "user:123:exists" in key

    def test_user_exists_with_str_id(self) -> None:
        """user_exists() со строкой."""
        key = RedisKeys.user_exists("456")
        assert "user:456:exists" in key

    def test_recipe_count_with_int_id(self) -> None:
        """recipe_count() с целым числом."""
        key = RedisKeys.recipe_count(789)
        assert "user:789:recipe_count" in key

    def test_recipe_count_with_str_id(self) -> None:
        """recipe_count() со строкой."""
        key = RedisKeys.recipe_count("101112")
        assert "user:101112:recipe_count" in key

    def test_user_init_lock_with_int_id(self) -> None:
        """user_init_lock() с целым числом."""
        key = RedisKeys.user_init_lock(999)
        assert "lock:user_init:999" in key

    def test_user_init_lock_with_str_id(self) -> None:
        """user_init_lock() со строкой."""
        key = RedisKeys.user_init_lock("555")
        assert "lock:user_init:555" in key

    def test_user_categories_converts_to_int(self) -> None:
        """user_categories() приводит ID к int."""
        key = RedisKeys.user_categories("123")
        assert "user:123:categories" in key

    def test_user_last_recipe_messages(self) -> None:
        """user_last_recipe_messages()."""
        key = RedisKeys.user_last_recipe_messages(42)
        assert "user:42:last_recipe_messages" in key

    def test_user_pipeline_ids(self) -> None:
        """user_pipeline_ids()."""
        key = RedisKeys.user_pipeline_ids(100)
        assert "user:100:pipeline_ids" in key

    def test_user_progress_message(self) -> None:
        """user_progress_message()."""
        key = RedisKeys.user_progress_message(77)
        assert "user:77:progress_message" in key


class TestRedisKeysCategoryKeys:
    """Тесты для ключей категорий."""

    def test_category_by_slug(self) -> None:
        """category_by_slug() с названием slug."""
        key = RedisKeys.category_by_slug("desserts")
        assert "category:by_slug:desserts" in key

    def test_category_by_slug_with_special_chars(self) -> None:
        """category_by_slug() с спецсимволами."""
        key = RedisKeys.category_by_slug("main_course-2024")
        assert "category:by_slug:main_course-2024" in key

    def test_slug_init_lock(self) -> None:
        """slug_init_lock()."""
        key = RedisKeys.slug_init_lock("pasta")
        assert "lock:slug_init:pasta" in key

    def test_all_category(self) -> None:
        """all_category()."""
        key = RedisKeys.all_category()
        assert "categories:all" in key

    def test_catergory_lock(self) -> None:
        """catergory_lock() (note: typo in method name)."""
        key = RedisKeys.catergory_lock()
        assert "lock:category" in key


class TestRedisKeysComplexKeys:
    """Тесты для составных ключей."""

    def test_user_recipes_ids_and_titles_with_int_ids(self) -> None:
        """user_recipes_ids_and_titles() с целыми числами."""
        key = RedisKeys.user_recipes_ids_and_titles(10, 20)
        assert "user:10" in key
        assert "category:20" in key
        assert "recipes_ids_titles" in key

    def test_user_recipes_ids_and_titles_with_str_ids(self) -> None:
        """user_recipes_ids_and_titles() со строками."""
        key = RedisKeys.user_recipes_ids_and_titles("10", "20")
        assert "user:10" in key
        assert "category:20" in key

    def test_user_pipeline_draft_with_int_ids(self) -> None:
        """user_pipeline_draft() с целыми числами."""
        key = RedisKeys.user_pipeline_draft(5, 15)
        assert "user:5" in key
        assert "pipeline:15" in key

    def test_user_pipeline_draft_with_str_ids(self) -> None:
        """user_pipeline_draft() со строками."""
        key = RedisKeys.user_pipeline_draft("5", "15")
        assert "user:5" in key
        assert "pipeline:15" in key

    def test_user_recipe_action(self) -> None:
        """user_recipe_action() с действием."""
        key = RedisKeys.user_recipe_action(100, "like")
        assert "user:100" in key
        assert "recipe_action:like" in key

    def test_user_recipe_action_with_different_actions(self) -> None:
        """user_recipe_action() с разными действиями."""
        actions = ["view", "like", "share", "edit", "delete"]

        for action in actions:
            key = RedisKeys.user_recipe_action(1, action)
            assert f"recipe_action:{action}" in key

    def test_user_url_candidate_state(self) -> None:
        """user_url_candidate_state() с session ID."""
        key = RedisKeys.user_url_candidate_state(42, "sid_12345")
        assert "user:42" in key
        assert "url_candidate:sid_12345" in key

    def test_user_webapp_recipe_draft(self) -> None:
        """user_webapp_recipe_draft() для Telegram WebApp."""
        key = RedisKeys.user_webapp_recipe_draft(88, 999)
        assert "user:88" in key
        assert "webapp:recipe:999" in key
        assert "draft" in key


class TestRedisKeysBroadcastKeys:
    """Тесты для ключей рассылок."""

    def test_broadcast_worker_lock_default_scope(self) -> None:
        """broadcast_worker_lock() с дефолтным scope."""
        key = RedisKeys.broadcast_worker_lock()
        assert "lock:broadcast_worker:main" in key

    def test_broadcast_worker_lock_custom_scope(self) -> None:
        """broadcast_worker_lock() с кастомным scope."""
        key = RedisKeys.broadcast_worker_lock("premium")
        assert "lock:broadcast_worker:premium" in key

    def test_broadcast_worker_lock_different_scopes(self) -> None:
        """broadcast_worker_lock() с разными scope."""
        scopes = ["main", "premium", "vip", "test"]

        for scope in scopes:
            key = RedisKeys.broadcast_worker_lock(scope)
            assert f"broadcast_worker:{scope}" in key


class TestRedisKeysUniqueness:
    """Тесты на уникальность ключей."""

    def test_different_user_ids_produce_different_keys(self) -> None:
        """Разные user_id → разные ключи."""
        key1 = RedisKeys.user_exists(1)
        key2 = RedisKeys.user_exists(2)

        assert key1 != key2

    def test_different_categories_produce_different_keys(self) -> None:
        """Разные категории → разные ключи."""
        key1 = RedisKeys.category_by_slug("pasta")
        key2 = RedisKeys.category_by_slug("desserts")

        assert key1 != key2

    def test_same_parameters_produce_same_key(self) -> None:
        """Одинаковые параметры → одинаковый ключ."""
        key1 = RedisKeys.user_recipes_ids_and_titles(10, 20)
        key2 = RedisKeys.user_recipes_ids_and_titles(10, 20)

        assert key1 == key2

    def test_different_scopes_produce_different_broadcast_locks(self) -> None:
        """Разные scope → разные broadcast locks."""
        key1 = RedisKeys.broadcast_worker_lock("main")
        key2 = RedisKeys.broadcast_worker_lock("premium")

        assert key1 != key2


class TestRedisKeysEdgeCases:
    """Тесты граничных случаев."""

    def test_large_user_id(self) -> None:
        """Большой user_id."""
        large_id = 9999999999
        key = RedisKeys.user_exists(large_id)
        assert str(large_id) in key

    def test_zero_user_id(self) -> None:
        """User ID = 0."""
        key = RedisKeys.user_exists(0)
        assert "user:0" in key

    def test_slug_with_underscores_and_dashes(self) -> None:
        """Slug с подчеркиваниями и дефисами."""
        slug = "main_course-special-2024"
        key = RedisKeys.category_by_slug(slug)
        assert slug in key

    def test_action_with_underscores(self) -> None:
        """Action с подчеркиванием."""
        key = RedisKeys.user_recipe_action(1, "user_like_action")
        assert "user_like_action" in key

    def test_long_session_id(self) -> None:
        """Длинный session ID."""
        long_sid = "a" * 100
        key = RedisKeys.user_url_candidate_state(1, long_sid)
        assert long_sid in key
