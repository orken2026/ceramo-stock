import pytest

from app.config import ConfigError, load_settings

GOOD = {
    "BOT_TOKEN": "123456789:AAH" + "x" * 32,
    "ADMIN_TELEGRAM_ID": "1000",
    "ONEC_ODATA_URL": "https://1c.test/base/odata/standard.odata",
    "ONEC_USER": "Пайдаланушы",
    "ONEC_PASSWORD": "secret-value",
    "PUBLIC_URL": "https://stock.test",
}


@pytest.fixture
def env(monkeypatch):
    for name in [*GOOD, "RENDER_EXTERNAL_URL"]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("app.config.load_dotenv", lambda: None)

    def apply(**values):
        for name, value in values.items():
            monkeypatch.setenv(name, value)

    return apply


def test_good_settings_load(env):
    env(**GOOD)
    settings = load_settings()
    assert settings.public_url == "https://stock.test"
    assert settings.onec.user == "Пайдаланушы"


def test_every_problem_is_reported_at_once_without_values(env):
    env(BOT_TOKEN="Асабай Өркен", PUBLIC_URL="ceramo-stock.onrender.com")
    with pytest.raises(ConfigError) as caught:
        load_settings()
    message = str(caught.value)
    for expected in ("ADMIN_TELEGRAM_ID is not set", "ONEC_USER is not set", "ONEC_PASSWORD is not set",
                     "BOT_TOKEN does not look like", "PUBLIC_URL must start"):
        assert expected in message
    assert "Асабай" not in message


def test_render_address_replaces_a_broken_public_url(env):
    env(**{**GOOD, "PUBLIC_URL": "ceramo-stock.onrender.com"}, RENDER_EXTERNAL_URL="https://ceramo-stock.onrender.com")
    assert load_settings().public_url == "https://ceramo-stock.onrender.com"
