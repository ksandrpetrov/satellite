"""Криптографические утилиты приложения.

В отдельный пакет вынесено всё, что касается шифрования пользовательских
секретов и проверки подписей. Domain-логика календаря не должна знать про
ключи: она получает уже расшифрованные ``ProviderCredentials``.
"""

from .token_vault import (
    InvalidEncryptionKeyError,
    ProviderCredentials,
    TokenDecryptError,
    TokenVault,
)

__all__ = [
    "InvalidEncryptionKeyError",
    "ProviderCredentials",
    "TokenDecryptError",
    "TokenVault",
]
