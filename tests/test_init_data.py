import pytest

from satellite.web.init_data import InitDataError, validate_init_data


def test_validate_init_data_empty():
    with pytest.raises(InitDataError) as exc:
        validate_init_data("", bot_token="1:token")
    assert exc.value.code == "no_init_data"


def test_validate_init_data_bad_token():
    from tests.test_web_server import BOT_TOKEN, _make_init_data

    data = _make_init_data(1, token=BOT_TOKEN)
    with pytest.raises(InitDataError) as exc:
        validate_init_data(data, bot_token="wrong:token")
    assert exc.value.code == "bad_signature"
