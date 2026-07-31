"""Шифрование пользовательских credentials (Fernet).

Хранилище никогда не получает токены в открытом виде: они проходят через
``TokenVault.encrypt`` и сохраняются в ``UserRecord.encrypted_credentials``
как base64-строка. Расшифровка делается ровно на время выполнения CalDAV-операции.
Тем же ключом отдельный типизированный API шифрует пользовательские исключения
названий встреч; открытые названия в ``users.json`` не попадают.

Ключ берётся из env-переменной ``TOKEN_ENCRYPTION_KEY`` — urlsafe base64
длиной 32 байта (``cryptography.fernet.Fernet.generate_key()``). При отсутствии
ключа бот отказывается стартовать: терять токены при ротации недопустимо.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken


class InvalidEncryptionKeyError(ValueError):
    """Ключ шифрования отсутствует или имеет неверный формат."""


class TokenDecryptError(RuntimeError):
    """Не удалось расшифровать токен — повреждение данных или смена ключа."""


@dataclass(frozen=True)
class ProviderCredentials:
    """Учётные данные пользователя для конкретного calendar provider.

    Для Mail.ru это пара ``(login, app_password)``: app password — это
    сервисный токен, который пользователь выпускает в личном кабинете
    Mail.ru для внешних приложений. Для других провайдеров поля могут
    интерпретироваться иначе, но обязаны быть строками.
    """

    login: str
    secret: str

    def is_empty(self) -> bool:
        return not (self.login.strip() and self.secret.strip())


@dataclass(frozen=True)
class EventTitleOverridePayload:
    """Одно явное состояние title внутри зашифрованного payload."""

    title: str
    excluded: bool


@dataclass(frozen=True)
class EventTitleOverridesPayload:
    """Типизированный payload персональных исключений встреч."""

    overrides: tuple[EventTitleOverridePayload, ...] = ()


class TokenVault:
    """Симметричное шифрование credentials через Fernet.

    Inputs/outputs — только типизированные payload и base64-blob. Класс
    специально не принимает «голый str» в encrypt-методах и не возвращает
    расшифрованную строку: это исключает случайный leak через логирование
    промежуточных значений.
    """

    def __init__(self, encryption_key: str) -> None:
        key = (encryption_key or "").strip()
        if not key:
            raise InvalidEncryptionKeyError(
                "TOKEN_ENCRYPTION_KEY is required. Generate it via "
                '`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.'
            )
        try:
            self._fernet = Fernet(key.encode("ascii"))
        except (ValueError, TypeError) as exc:
            raise InvalidEncryptionKeyError(
                "TOKEN_ENCRYPTION_KEY is not a valid Fernet key (32-byte urlsafe base64)."
            ) from exc

    def encrypt(self, credentials: ProviderCredentials) -> str:
        payload = json.dumps(
            {"login": credentials.login, "secret": credentials.secret},
            ensure_ascii=False,
        ).encode("utf-8")
        return self._fernet.encrypt(payload).decode("ascii")

    def decrypt(self, blob: str) -> ProviderCredentials:
        try:
            raw = self._fernet.decrypt((blob or "").encode("ascii"))
        except (InvalidToken, ValueError) as exc:
            raise TokenDecryptError(
                "Failed to decrypt stored credentials (key rotated or data corrupted)."
            ) from exc
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise TokenDecryptError("Decrypted payload is not valid JSON.") from exc
        if not isinstance(data, dict):
            raise TokenDecryptError("Decrypted payload is not a JSON object.")
        login = str(data.get("login") or "")
        secret = str(data.get("secret") or "")
        return ProviderCredentials(login=login, secret=secret)

    def encrypt_event_title_overrides(self, payload: EventTitleOverridesPayload) -> str:
        """Шифрует список title override без generic string API."""
        raw = json.dumps(
            {
                "version": 1,
                "overrides": [
                    {"title": item.title, "excluded": item.excluded} for item in payload.overrides
                ],
            },
            ensure_ascii=False,
        ).encode("utf-8")
        return self._fernet.encrypt(raw).decode("ascii")

    def decrypt_event_title_overrides(self, blob: str) -> EventTitleOverridesPayload:
        """Расшифровывает и строго валидирует payload исключений."""
        try:
            raw = self._fernet.decrypt((blob or "").encode("ascii"))
        except (InvalidToken, ValueError) as exc:
            raise TokenDecryptError(
                "Failed to decrypt stored event-title overrides (key rotated or data corrupted)."
            ) from exc
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise TokenDecryptError(
                "Decrypted event-title override payload is not valid JSON."
            ) from exc
        if not isinstance(data, dict) or data.get("version") != 1:
            raise TokenDecryptError("Decrypted event-title override payload is invalid.")
        raw_overrides = data.get("overrides")
        if not isinstance(raw_overrides, list):
            raise TokenDecryptError("Decrypted event-title overrides must be a JSON array.")

        overrides: list[EventTitleOverridePayload] = []
        for item in raw_overrides:
            if not isinstance(item, dict):
                raise TokenDecryptError("Decrypted event-title override entry is invalid.")
            title = item.get("title")
            excluded = item.get("excluded")
            if not isinstance(title, str) or not title.strip() or not isinstance(excluded, bool):
                raise TokenDecryptError("Decrypted event-title override entry is invalid.")
            overrides.append(EventTitleOverridePayload(title=title, excluded=excluded))
        return EventTitleOverridesPayload(overrides=tuple(overrides))
