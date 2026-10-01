from app.core.config import Settings


def test_defaults_without_env_file() -> None:
    settings = Settings(_env_file=None)

    assert settings.api_prefix == "/api/v1"
    assert settings.database_url.startswith("mysql+pymysql://")
    assert "pulse_lifecycle_dev" in settings.database_url
    assert settings.db_pool_size == 10


def test_cors_origins_accepts_comma_separated_string() -> None:
    settings = Settings(_env_file=None, cors_origins="http://localhost:5173, http://127.0.0.1:5173")

    assert settings.cors_origins == ["http://localhost:5173", "http://127.0.0.1:5173"]


def test_cors_origins_empty_means_disabled() -> None:
    settings = Settings(_env_file=None, cors_origins="")

    assert settings.cors_origins == []
