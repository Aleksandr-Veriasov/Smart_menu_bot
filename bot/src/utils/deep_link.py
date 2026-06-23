# Telegram deep-link `start` payloads: `share_<token>` (и легаси `share:<token>`).
_SHARE_PREFIXES = ("share_", "share:")


def parse_shared_token(args: str | None) -> str | None:
    """Извлекает токен шаринга из payload команды /start."""
    if not args:
        return None
    for prefix in _SHARE_PREFIXES:
        if args.startswith(prefix):
            return args.removeprefix(prefix).strip() or None
    return None
