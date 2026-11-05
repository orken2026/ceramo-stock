import time

import pytest
from conftest import BOT_TOKEN, sign_init_data

from app.tg_auth import InitDataError, verify_init_data


def check(init_data: str, **kwargs):
    return verify_init_data(init_data, BOT_TOKEN, 86400, **kwargs)


def test_valid_data_gives_the_user():
    user = check(sign_init_data(555))
    assert user.id == 555
    assert user.first_name == "Тест"


def test_newer_signature_field_is_part_of_the_check():
    assert check(sign_init_data(555, signature="abc")).id == 555


@pytest.mark.parametrize("bad", ["", "hash=", "user=1", "a", "%zz=1&&"])
def test_garbage_is_rejected(bad):
    with pytest.raises(InitDataError):
        check(bad)


def test_other_bots_token_is_rejected():
    with pytest.raises(InitDataError):
        check(sign_init_data(555, token="999:OTHER"))


def test_changing_the_user_id_breaks_the_hash():
    tampered = sign_init_data(555).replace("555", "1000")
    with pytest.raises(InitDataError):
        check(tampered)


def test_old_data_is_rejected():
    with pytest.raises(InitDataError):
        check(sign_init_data(555, auth_date=int(time.time()) - 90000))


def test_data_from_the_future_is_rejected():
    with pytest.raises(InitDataError):
        check(sign_init_data(555, auth_date=int(time.time()) + 3600))


def test_repeated_fields_are_rejected():
    with pytest.raises(InitDataError):
        check(sign_init_data(555) + "&user=%7B%22id%22%3A1000%7D")
