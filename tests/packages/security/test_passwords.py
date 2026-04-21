import pytest

from packages.security import passwords


class TestHashPassword:
    """Тесты базовой функциональности hash_password()."""

    def test_hash_returns_string(self) -> None:
        """hash_password() возвращает строку."""
        hashed = passwords.hash_password("test_password")
        assert isinstance(hashed, str)

    def test_hash_is_bcrypt_format(self) -> None:
        """Хэш в формате bcrypt ($2...$...)."""
        hashed = passwords.hash_password("test_password")
        assert hashed.startswith("$2")

    def test_each_hash_is_unique(self) -> None:
        """Каждый вызов даёт разный хэш (разная соль)."""
        password = "same_password"
        hash1 = passwords.hash_password(password)
        hash2 = passwords.hash_password(password)

        assert hash1 != hash2
        assert len(hash1) == len(hash2)

    def test_hash_empty_string(self) -> None:
        """Пустая строка хэшируется корректно."""
        hashed = passwords.hash_password("")
        assert isinstance(hashed, str)
        assert hashed.startswith("$2")

    def test_hash_long_password(self) -> None:
        """Длинный пароль (>72 символа) хэшируется корректно.

        Замечание: bcrypt ограничивает до 72 байт, но это обработано passlib.
        """
        long_password = "a" * 100
        hashed = passwords.hash_password(long_password)
        assert isinstance(hashed, str)
        assert hashed.startswith("$2")

    def test_hash_special_characters(self) -> None:
        """Пароль со спецсимволами."""
        password = "p@$$w0rd!#%&*()_+-={}[]|:;<>?,./~`"
        hashed = passwords.hash_password(password)
        assert isinstance(hashed, str)
        assert hashed.startswith("$2")

    def test_hash_unicode_password(self) -> None:
        """Пароль с Unicode символами."""
        password = "пароль_русский_🔐"
        hashed = passwords.hash_password(password)
        assert isinstance(hashed, str)
        assert hashed.startswith("$2")

    def test_hash_whitespace_preserved(self) -> None:
        """Пароль с пробелами — пробелы учитываются в хэше."""
        hash_with_space = passwords.hash_password("pass word")
        hash_without_space = passwords.hash_password("password")

        # Они должны быть разными
        assert hash_with_space != hash_without_space

    def test_hash_without_pepper_when_pepper_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Если pepper=None, хэш идёт напрямую без HMAC."""
        monkeypatch.setattr(passwords, "_PEPPER", None)

        password = "test_password"
        hashed = passwords.hash_password(password)

        assert isinstance(hashed, str)
        assert hashed.startswith("$2")

    def test_hash_with_pepper_when_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Если pepper установлен, он применяется к паролю перед хэшем."""
        test_pepper = "my_secret_pepper"
        monkeypatch.setattr(passwords, "_PEPPER", test_pepper)

        password = "test_password"
        hashed = passwords.hash_password(password)

        assert isinstance(hashed, str)
        assert hashed.startswith("$2")

    def test_hash_differs_with_and_without_pepper(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Хэш одного пароля разный с pepper и без pepper."""
        password = "test_password"

        # Хэш без pepper
        monkeypatch.setattr(passwords, "_PEPPER", None)
        hash_without = passwords.hash_password(password)

        # Хэш с pepper
        monkeypatch.setattr(passwords, "_PEPPER", "secret_pepper")
        hash_with = passwords.hash_password(password)

        # Хэши разные
        assert hash_without != hash_with

    def test_hash_length_is_consistent(self) -> None:
        """bcrypt хэш всегда одинаковой длины (60 символов)."""
        passwords_to_test = [
            "short",
            "medium_password_123",
            "a" * 100,
            "спецсимволы!@#$",
            "",
        ]

        for pwd in passwords_to_test:
            hashed = passwords.hash_password(pwd)
            assert len(hashed) == 60, f"Хэш для '{pwd}' имеет неверную длину"

    def test_hash_is_deterministic_with_pepper(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """С pepper HMAC-часть детерминирована (хотя bcrypt-соль разная).

        Проверяем, что verify() может подтвердить с тем же pepper.
        """
        test_pepper = "consistent_pepper"
        monkeypatch.setattr(passwords, "_PEPPER", test_pepper)

        password = "test_password"
        hash1 = passwords.hash_password(password)

        # Хэш содержит результат bcrypt(HMAC(pepper, password))
        # Проверяем, что verify() может подтвердить с тем же pepper
        from packages.security.passwords import verify_password

        assert verify_password(password, hash1) is True


class TestVerifyPassword:
    """Тесты функциональности verify_password()."""

    def test_verify_correct_password(self) -> None:
        """Корректный пароль проходит проверку."""
        password = "correct_password"
        hashed = passwords.hash_password(password)

        assert passwords.verify_password(password, hashed) is True

    def test_verify_incorrect_password(self) -> None:
        """Неверный пароль не проходит проверку."""
        password = "correct_password"
        wrong_password = "wrong_password"
        hashed = passwords.hash_password(password)

        assert passwords.verify_password(wrong_password, hashed) is False

    def test_verify_empty_password(self) -> None:
        """Пустой пароль можно хэшировать и проверять."""
        password = ""
        hashed = passwords.hash_password(password)

        assert passwords.verify_password("", hashed) is True
        assert passwords.verify_password("something", hashed) is False

    def test_verify_case_sensitive(self) -> None:
        """Проверка регистра-чувствительна."""
        password = "MyPassword"
        hashed = passwords.hash_password(password)

        assert passwords.verify_password("MyPassword", hashed) is True
        assert passwords.verify_password("mypassword", hashed) is False
        assert passwords.verify_password("MYPASSWORD", hashed) is False

    def test_verify_with_special_characters(self) -> None:
        """Пароль со спецсимволами."""
        password = "p@$$w0rd!#%&*()_+-={}[]|:;<>?,./~`"
        hashed = passwords.hash_password(password)

        assert passwords.verify_password(password, hashed) is True
        assert passwords.verify_password("p@$$w0rd", hashed) is False

    def test_verify_with_unicode(self) -> None:
        """Пароль с Unicode символами."""
        password = "пароль_русский_🔐"
        hashed = passwords.hash_password(password)

        assert passwords.verify_password(password, hashed) is True
        assert passwords.verify_password("пароль_русский", hashed) is False

    def test_verify_with_whitespace(self) -> None:
        """Пробелы в пароле учитываются."""
        password = "pass word"
        hashed = passwords.hash_password(password)

        assert passwords.verify_password("pass word", hashed) is True
        assert passwords.verify_password("password", hashed) is False

    def test_verify_long_password(self) -> None:
        """Длинный пароль (>72 символа)."""
        password = "a" * 100
        hashed = passwords.hash_password(password)

        assert passwords.verify_password(password, hashed) is True
        assert passwords.verify_password("a" * 99, hashed) is False

    def test_verify_with_pepper_when_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Верификация с pepper."""
        test_pepper = "secret_pepper"
        monkeypatch.setattr(passwords, "_PEPPER", test_pepper)

        password = "test_password"
        hashed = passwords.hash_password(password)

        assert passwords.verify_password(password, hashed) is True

    def test_verify_fails_with_different_pepper(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Если pepper другой, верификация не пройдёт."""
        password = "test_password"

        # Хэш с одним pepper
        monkeypatch.setattr(passwords, "_PEPPER", "pepper1")
        hashed = passwords.hash_password(password)

        # Проверка с другим pepper
        monkeypatch.setattr(passwords, "_PEPPER", "pepper2")
        assert passwords.verify_password(password, hashed) is False

    def test_verify_fails_when_pepper_removed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Если pepper был установлен при хэшировании, но удален — верификация не пройдёт."""
        password = "test_password"

        # Хэш с pepper
        monkeypatch.setattr(passwords, "_PEPPER", "secret_pepper")
        hashed = passwords.hash_password(password)

        # Проверка без pepper
        monkeypatch.setattr(passwords, "_PEPPER", None)
        assert passwords.verify_password(password, hashed) is False

    def test_verify_returns_bool(self) -> None:
        """verify_password() всегда возвращает bool, никогда не исключение."""
        password = "test_password"
        hashed = passwords.hash_password(password)

        result = passwords.verify_password(password, hashed)
        assert isinstance(result, bool)

        result = passwords.verify_password("wrong", hashed)
        assert isinstance(result, bool)

    def test_verify_invalid_hash_raises_error(self) -> None:
        """Невалидный хэш выбрасывает исключение при проверке."""
        from passlib.exc import UnknownHashError

        password = "test_password"
        invalid_hash = "not_a_valid_bcrypt_hash"

        with pytest.raises(UnknownHashError):
            passwords.verify_password(password, invalid_hash)


class TestNeedsRehash:
    """Тесты функциональности needs_rehash()."""

    def test_needs_rehash_returns_bool(self) -> None:
        """needs_rehash() возвращает bool."""
        password = "test_password"
        hashed = passwords.hash_password(password)

        result = passwords.needs_rehash(hashed)
        assert isinstance(result, bool)

    def test_current_hash_does_not_need_rehash(self) -> None:
        """Текущий хэш (bcrypt с 12 rounds) не требует rehash."""
        password = "test_password"
        hashed = passwords.hash_password(password)

        assert passwords.needs_rehash(hashed) is False

    def test_needs_rehash_with_valid_hash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Проверка needs_rehash на корректном хэше."""
        password = "test_password"

        # Хэш с текущей конфигурацией
        monkeypatch.setattr(passwords, "_PEPPER", None)
        hashed = passwords.hash_password(password)

        assert passwords.needs_rehash(hashed) is False

    def test_needs_rehash_invalid_hash_raises_error(self) -> None:
        """Невалидный хэш выбрасывает исключение."""
        from passlib.exc import UnknownHashError

        invalid_hash = "not_a_valid_bcrypt_hash"

        with pytest.raises(UnknownHashError):
            passwords.needs_rehash(invalid_hash)

    def test_multiple_hashes_none_need_rehash(self) -> None:
        """Несколько хэшей, созданных функцией, не требуют rehash."""
        test_passwords = [
            "password1",
            "test123",
            "сложный_пароль_🔐",
            "",
            "a" * 100,
        ]

        for pwd in test_passwords:
            hashed = passwords.hash_password(pwd)
            assert passwords.needs_rehash(hashed) is False


class TestPasswordIntegration:
    """Интеграционные тесты: hash + verify + rehash."""

    def test_full_password_flow(self) -> None:
        """Полный цикл: hash → verify → rehash."""
        password = "user_password_123"

        # Этап 1: Хэширование
        hashed = passwords.hash_password(password)
        assert isinstance(hashed, str)
        assert hashed.startswith("$2")

        # Этап 2: Верификация с правильным паролем
        assert passwords.verify_password(password, hashed) is True

        # Этап 3: Верификация с неправильным паролем
        assert passwords.verify_password("wrong_password", hashed) is False

        # Этап 4: Проверка нужно ли перехэшировать
        assert passwords.needs_rehash(hashed) is False

    def test_password_flow_with_pepper(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Полный цикл с pepper."""
        monkeypatch.setattr(passwords, "_PEPPER", "system_pepper")

        password = "secure_password"
        hashed = passwords.hash_password(password)

        assert passwords.verify_password(password, hashed) is True
        assert passwords.needs_rehash(hashed) is False

    def test_multiple_users_different_hashes(self) -> None:
        """Разные пользователи — разные хэши (даже одинаковые пароли)."""
        common_password = "common_password"

        hash1 = passwords.hash_password(common_password)
        hash2 = passwords.hash_password(common_password)

        assert hash1 != hash2
        assert passwords.verify_password(common_password, hash1) is True
        assert passwords.verify_password(common_password, hash2) is True
