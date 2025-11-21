from devtriage.capture import sanitize_env, sanitize_value


def test_sanitize_env_redacts_sensitive_keys():
    env = {
        "API_KEY": "abcd",
        "normal": "value",
        "secret_token": "hunter2",
    }
    sanitized = sanitize_env(env)
    assert sanitized["API_KEY"] == "***REDACTED***"
    assert sanitized["secret_token"] == "***REDACTED***"
    assert sanitized["normal"] == "value"


def test_sanitize_value_redacts_strings():
    payload = {"password": "super-secret", "nested": ["token-123", "ok"]}
    result = sanitize_value(payload)
    assert result["password"] == "***REDACTED***"
    assert result["nested"][0] == "***REDACTED***"

