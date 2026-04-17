"""Regex-based secret redaction using google-re2."""
from kalevala.scrubber import Scrubber


def test_anthropic_key_redacted():
    s = Scrubber()
    result, redactions = s.scrub("my key is sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_abc")
    assert "sk-ant" not in result
    assert "[REDACTED:anthropic]" in result
    assert redactions["anthropic"] == 1


def test_openai_key_redacted_but_not_anthropic_prefix():
    s = Scrubber()
    # an Anthropic key should match pattern #1 (anthropic), not pattern #2 (openai)
    _, r = s.scrub("sk-ant-api03-" + "x" * 60)
    assert r.get("anthropic") == 1
    assert r.get("openai", 0) == 0


def test_openai_proj_key_redacted():
    s = Scrubber()
    result, r = s.scrub("key: sk-proj-" + "x" * 50)
    assert "sk-proj" not in result
    assert r["openai"] == 1


def test_aws_access_key_redacted():
    s = Scrubber()
    result, _ = s.scrub("aws: AKIAIOSFODNN7EXAMPLE")
    assert "AKIA" not in result
    assert "[REDACTED:aws_access_key]" in result


def test_github_token_redacted():
    s = Scrubber()
    result, _ = s.scrub("token=ghp_" + "A" * 36)
    assert "ghp_" not in result


def test_bearer_token_redacted():
    s = Scrubber()
    result, _ = s.scrub("Authorization: Bearer eyJabcdefg.some.jwt")
    assert "Bearer " not in result


def test_jwt_redacted():
    s = Scrubber()
    tok = "eyJhbGciOiJIUzI1NiJ9." + "A" * 40 + "." + "B" * 30
    result, _ = s.scrub(f"jwt={tok}")
    assert "eyJhbGciOiJIUzI1NiJ9" not in result


def test_private_key_redacted():
    s = Scrubber()
    body = "-----BEGIN RSA PRIVATE KEY-----\nABCDEFG\nHIJKLMN\n-----END RSA PRIVATE KEY-----"
    result, _ = s.scrub(f"key: {body}")
    assert "BEGIN RSA PRIVATE KEY" not in result


def test_env_var_unquoted_redacted():
    s = Scrubber()
    # .env-style unquoted
    result, r = s.scrub("API_KEY=sk9f3jkl29fjALKSDF092ijF00k3")
    assert "sk9f3jkl29fjALKSDF092ijF00k3" not in result
    assert r.get("env_var") == 1


def test_env_var_quoted_redacted():
    s = Scrubber()
    result, _ = s.scrub('api_key: "aB3dEfGh1jKlMnOpQrStUv"')
    assert "aB3dEfGh1jKlMnOpQrStUv" not in result


def test_prose_not_false_positive():
    s = Scrubber()
    # prose with spaces should survive
    text = "The api_key: documented in rfc 1234, see also the bearer token section"
    result, r = s.scrub(text)
    assert "documented in rfc" in result
    assert r.get("env_var", 0) == 0


def test_sentinel_not_re_matched():
    """A sentinel in intermediate state shouldn't be re-scrubbed by later patterns."""
    s = Scrubber()
    text = f"password=ABCDEF{'x' * 20}"  # triggers env_var
    result, r = s.scrub(text)
    # redaction shouldn't cascade
    assert result.count("[REDACTED:") == 1


def test_rewrite_sentinel_to_display():
    s = Scrubber()
    raw, _ = s.scrub("key: sk-ant-api03-" + "x" * 40)
    # final output uses [REDACTED:<type>] not sentinel guillemets
    assert "«" not in raw
    assert "»" not in raw
    assert "[REDACTED:anthropic]" in raw
