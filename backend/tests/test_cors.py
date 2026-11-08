from app.config import Settings


def test_react_development_origin_is_in_the_default_allowlist():
    default = Settings.model_fields["allowed_origins"].default
    origins = [origin.strip() for origin in default.split(",")]
    assert "http://localhost:5173" in origins
    assert "http://localhost:3000" in origins
