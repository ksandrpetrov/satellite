"""Concurrent refresh workers own separate sessions, and shutdown drains them."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock
from unittest.mock import patch

from satellite.calendar.caldav_client import CalDAVService


def test_parallel_http_requests_use_exclusive_sessions_and_close_after_release():
    both_entered = Barrier(3)
    release = Event()
    clients = []
    guard = Lock()

    class Session:
        def __init__(self):
            self.active = False
            self.closed = False
            clients.append(self)

        def request(self, *args, **kwargs):
            with guard:
                assert not self.active and not self.closed
                self.active = True
            both_entered.wait(timeout=5)
            assert release.wait(5)
            with guard:
                self.active = False
            return object()

        def close(self):
            with guard:
                assert not self.active
                self.closed = True

    with patch("satellite.calendar.caldav_client._new_http_session", Session):
        service = CalDAVService(
            caldav_url="https://cal/", login="me@example.com", app_password="pw"
        )
        with ThreadPoolExecutor() as pool:
            futures = [pool.submit(service._http_get, "https://cal/event") for _ in range(2)]
            try:
                both_entered.wait(timeout=5)
                assert len(clients) == 2
                closing = pool.submit(service.close)
            finally:
                release.set()
            for future in futures:
                assert future.result(timeout=5) is not None
            closing.result(timeout=5)
        assert all(client.closed for client in clients)
        service.close()


def test_closed_client_cannot_restart_discovery():
    import pytest

    from satellite.calendar.caldav_client import CalDAVError

    service = CalDAVService(caldav_url="https://cal/", login="me@example.com", app_password="pw")
    service.close()
    with patch.object(service, "_do_discovery") as discover:
        with pytest.raises(CalDAVError, match="closed"):
            service.list_calendars()
        discover.assert_not_called()
