"""Exact ATTENDEE address matching for the connected calendar account."""

from __future__ import annotations


def attendee_matches_account(attendee: str, login: str) -> bool:
    account = login.strip().casefold()
    address = attendee.split(";", 1)[0].strip().casefold().removeprefix("mailto:")
    return bool(account and "@" in account and address == account)
