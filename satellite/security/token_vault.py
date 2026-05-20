"""Шифрование пользовательских credentials (Fernet).

Хранилище никогда не получает токены в открытом виде: они проходят через
``TokenVault.encrypt`` и сохраняются в ``UserRecord.encrypted_credentials``
как base64-строка. Расшифровка делается ровно на время выполнения CalDAV-операции.

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


class TokenVault:
    """Симметричное шифрование credentials через Fernet.

    Inputs/outputs — только ``ProviderCredentials`` и base64-blob. Класс
    специально не принимает «голый str» в encrypt и не возвращает его из
    decrypt: это исключает случайный leak через логирование промежуточных
    значений.
    """

    def __init__(self, encryption_key: str) -> None:
        key = (encryption_key or "").strip()
        if not key:
            raise InvalidEncryptionKeyError(
                "TOKEN_ENCRYPTION_KEY is required. Generate it via "
                "`python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"`."
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
