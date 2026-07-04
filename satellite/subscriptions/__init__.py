"""Per-user digest subscription settings (``logs/subscriptions.json``).

Фасад пакета. Раньше всё жило в одном ``subscriptions.py``; сейчас:

- :mod:`.record` — ``DigestSettings``, константы, validation helpers;
- :mod:`.store` — ``SubscriptionStore``, ``SubscriptionStorePersistenceError``.

Импорты ``from satellite.subscriptions import …`` не меняются.
"""

from .record import (
    ALLOWED_DIGEST_DAYS,
    DEFAULT_DIGEST_DAYS,
    DEFAULT_DIGEST_TIME,
    DEFAULT_DIGEST_TIMEZONE,
    DEFAULT_PENDING_DIGEST_TIME,
    DIGEST_DAYS_ALL,
    DIGEST_DAYS_WEEKDAYS,
    PENDING_DIGEST_DAYS_MASK_LEN,
    DigestSettings,
    Subscription,
    is_valid_pending_digest_days,
)
from .store import SubscriptionStore, SubscriptionStorePersistenceError

__all__ = [
    "ALLOWED_DIGEST_DAYS",
    "DEFAULT_DIGEST_DAYS",
    "DEFAULT_DIGEST_TIME",
    "DEFAULT_DIGEST_TIMEZONE",
    "DEFAULT_PENDING_DIGEST_TIME",
    "DIGEST_DAYS_ALL",
    "DIGEST_DAYS_WEEKDAYS",
    "PENDING_DIGEST_DAYS_MASK_LEN",
    "DigestSettings",
    "Subscription",
    "SubscriptionStore",
    "SubscriptionStorePersistenceError",
    "is_valid_pending_digest_days",
]
