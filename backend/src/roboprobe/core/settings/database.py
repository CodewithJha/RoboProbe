"""Database settings (docs/27 §4.1).

Layer: Kernel (L1).
"""

from pathlib import Path
from typing import Any, Literal, Self
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from pydantic import Field, SecretStr, model_validator

from roboprobe.core.settings._base import SettingsSection

__all__ = ["DatabaseSettings"]

_SCHEME = "postgresql"


class DatabaseSettings(SettingsSection):
    """PostgreSQL connection settings.

    When ``password_file`` is set and ``url`` has no password, the file content (stripped) is
    merged into ``url`` at load time, so consumers only ever read :attr:`url`.
    """

    url: SecretStr = Field(
        default=SecretStr("postgresql+psycopg://roboprobe@localhost:5432/roboprobe"),
        description=(
            "SQLAlchemy DSN of the RoboProbe database. Keep the password out of the URL and use "
            "`password_file` or the `db_password` secret file instead."
        ),
    )
    password_file: Path | None = Field(
        default=None,
        description="File holding the database password; merged into `url` [path].",
    )
    sslmode: Literal["disable", "allow", "prefer", "require", "verify-ca", "verify-full"] | None = (
        Field(
            default=None,
            description="PostgreSQL TLS policy; overrides an sslmode in the DSN when set.",
        )
    )
    pool_size: int = Field(default=5, gt=0, description="Connection pool size per process.")
    statement_timeout_ms: int = Field(
        default=30000, gt=0, description="Server-side statement timeout [ms]."
    )
    notify_channel: str = Field(
        default="roboprobe_events",
        pattern=r"^[a-z_][a-z0-9_]*$",
        description="PostgreSQL LISTEN/NOTIFY channel for live events.",
    )

    @model_validator(mode="before")
    @classmethod
    def _compose_connection_url(cls, data: Any) -> Any:  # noqa: ANN401 - pydantic raw input
        if not isinstance(data, dict):
            return data
        secret_file = data.get("password_file")
        sslmode = data.get("sslmode")
        if secret_file in (None, "") and sslmode is None:
            return data
        raw_url = data.get("url", cls.model_fields["url"].default)
        url = raw_url.get_secret_value() if isinstance(raw_url, SecretStr) else str(raw_url)
        if secret_file not in (None, ""):
            password_path = Path(secret_file)
            try:
                password = password_path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                msg = f"cannot read database.password_file {password_path}: {exc.strerror}"
                raise ValueError(msg) from None
            url = _with_password(url, password)
        if sslmode is not None:
            parts = urlsplit(url)
            query = [
                (key, value)
                for key, value in parse_qsl(parts.query, keep_blank_values=True)
                if key != "sslmode"
            ]
            query.append(("sslmode", str(sslmode)))
            url = urlunsplit(parts._replace(query=urlencode(query)))
        return {**data, "url": SecretStr(url)}

    @model_validator(mode="after")
    def _check_scheme(self) -> Self:
        scheme = urlsplit(self.url.get_secret_value()).scheme
        if scheme != _SCHEME and not scheme.startswith(f"{_SCHEME}+"):
            msg = "database.url must be a postgresql:// or postgresql+<driver>:// DSN"
            raise ValueError(msg)
        return self


def _with_password(url: str, password: str) -> str:
    """Insert ``password`` into a DSN that has a user; a password already in the URL wins."""
    parts = urlsplit(url)
    if parts.password is not None:
        return url  # docs/27 §4.1: the password file is used only if the URL has none.
    if parts.username is None:
        msg = "database.url needs a user name to attach the password from database.password_file"
        raise ValueError(msg)
    userinfo, _, hostinfo = parts.netloc.rpartition("@")
    netloc = f"{userinfo}:{quote(password, safe='')}@{hostinfo}"
    return urlunsplit(parts._replace(netloc=netloc))
