from pathlib import Path

import pytest

from roboprobe.core.errors import ConfigError
from roboprobe.core.settings import explain_sources, load_settings

pytestmark = pytest.mark.unit

TOKEN = "dummy-token-value"
PASSWORD = "p@ss:w/rd-very-secret"


def _assert_hidden(text: str) -> None:
    assert TOKEN not in text
    assert PASSWORD not in text
    assert "p%40ss" not in text


def test_secrets_are_masked_in_repr_and_dumps(
    settings_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ROBOPROBE_API__TOKEN", TOKEN)
    monkeypatch.setenv("ROBOPROBE_DATABASE__URL", f"postgresql+psycopg://rp:{PASSWORD}@db/rp")
    settings = load_settings()
    _assert_hidden(repr(settings))
    _assert_hidden(str(settings.model_dump()))
    _assert_hidden(settings.model_dump_json())
    assert settings.api.token is not None
    assert settings.api.token.get_secret_value() == TOKEN


def test_password_file_is_merged_into_dsn(settings_env: Path) -> None:
    password_file = settings_env / "pw"
    password_file.write_text(f"{PASSWORD}\n")
    settings = load_settings({"database.password_file": str(password_file)})
    assert (
        settings.database.url.get_secret_value()
        == "postgresql+psycopg://roboprobe:p%40ss%3Aw%2Frd-very-secret@localhost:5432/roboprobe"
    )
    _assert_hidden(repr(settings.database))


def test_password_in_url_wins_over_password_file(settings_env: Path) -> None:
    password_file = settings_env / "pw"
    password_file.write_text("from-file")
    url = "postgresql+psycopg://rp:inline@db/rp"
    settings = load_settings({"database": {"url": url, "password_file": str(password_file)}})
    assert settings.database.url.get_secret_value() == url


def test_password_file_needs_user_in_url(settings_env: Path) -> None:
    password_file = settings_env / "pw"
    password_file.write_text("x")
    with pytest.raises(ConfigError):
        load_settings(
            {"database": {"url": "postgresql+psycopg://db/rp", "password_file": str(password_file)}}
        )


def test_unreadable_password_file_is_a_config_error(settings_env: Path) -> None:
    with pytest.raises(ConfigError) as info:
        load_settings({"database.password_file": str(settings_env / "missing")})
    assert info.value.context["errors"][0]["loc"] == "database"  # type: ignore[index]


def test_secret_files_directory(settings_env: Path) -> None:
    secrets = settings_env / "secrets"
    (secrets / "db_password").write_text(PASSWORD)
    (secrets / "api_token").write_text(f"{TOKEN}\n")
    settings = load_settings()
    assert PASSWORD.replace("@", "%40") not in repr(settings)
    assert settings.database.password_file == secrets / "db_password"
    assert "%40" in settings.database.url.get_secret_value()
    assert settings.api.token is not None
    assert settings.api.token.get_secret_value() == TOKEN
    sources = explain_sources(settings)
    assert sources["api.token"] == sources["database.password_file"] == "secrets"


def test_env_beats_secret_files(settings_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (settings_env / "secrets" / "api_token").write_text("from-file")
    monkeypatch.setenv("ROBOPROBE_API__TOKEN", "from-env")
    settings = load_settings()
    assert settings.api.token is not None
    assert settings.api.token.get_secret_value() == "from-env"


def test_missing_secrets_dir_is_fine(settings_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROBOPROBE_SECRETS_DIR", str(settings_env / "absent"))
    assert load_settings().api.token is None
