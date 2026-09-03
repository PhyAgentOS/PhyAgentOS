from __future__ import annotations

import pytest

from PhyAgentOS.config.schema import AgentVerificationConfig
from PhyAgentOS.verification.engine import VerificationEngine
from PhyAgentOS.verification.service import (
    VerificationProviderSpec,
    VerificationServiceProcess,
    VerificationServiceSettings,
)


def _custom_spec(**overrides):
    value = {
        "provider_name": "custom",
        "model": "fixture-model",
        "api_base": "http://127.0.0.1:9000/v1",
        "temperature": 0.0,
        "max_tokens": 1024,
    }
    value.update(overrides)
    return value


def test_provider_spec_is_strict_and_normalizes_safe_values():
    spec = VerificationProviderSpec.model_validate(
        _custom_spec(
            api_base="http://127.0.0.1:9000/v1/",
            extra_headers={" X-Test ": " value "},
        )
    )
    assert spec.api_base == "http://127.0.0.1:9000/v1"
    assert spec.extra_headers == {"X-Test": "value"}


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"provider_name": "not-a-provider"}, "unknown verification provider"),
        ({"api_base": "relative/path"}, r"absolute HTTP\(S\) URL"),
        ({"api_base": "http://user:pass@example.test/v1"}, "credentials"),
        ({"api_base": "http://example.test:invalid/v1"}, "invalid port"),
        ({"api_base": "http://example.test:0/v1"}, "invalid port"),
        ({"api_base": "http://bad host.test/v1"}, "whitespace"),
        ({"api_base": "https://example.test/v1?token=value"}, "query or fragment"),
        ({"extra_headers": {"X-Test": "bad\nvalue"}}, "HTTP header"),
        ({"extra_headers": {"X-Test": "bad\x00value"}}, "HTTP header"),
        ({"extra_headers": {"Bad Header": "value"}}, "HTTP header"),
        ({"extra_headers": {"X-Test": "one", " x-test ": "two"}}, "duplicate"),
        ({"unknown": True}, "Extra inputs"),
    ],
)
def test_provider_spec_rejects_invalid_or_unknown_configuration(overrides, match):
    with pytest.raises(ValueError, match=match):
        VerificationProviderSpec.model_validate(_custom_spec(**overrides))


def test_provider_specific_required_fields_fail_closed():
    with pytest.raises(ValueError, match="custom verification provider requires api_base"):
        VerificationProviderSpec.model_validate(_custom_spec(api_base=None))
    with pytest.raises(ValueError, match="azure_openai verification requires"):
        VerificationProviderSpec.model_validate(
            {
                "provider_name": "azure_openai",
                "model": "deployment",
                "api_base": "https://example.openai.azure.com",
            }
        )
    with pytest.raises(ValueError, match="vllm verification provider requires api_base"):
        VerificationProviderSpec.model_validate(
            {"provider_name": "vllm", "model": "local-model"}
        )


def test_service_settings_rejects_invalid_token_and_bounds_request_size():
    spec = VerificationProviderSpec.model_validate(_custom_spec())
    with pytest.raises(ValueError, match="session_token"):
        VerificationServiceSettings(
            provider=spec,
            host="127.0.0.1",
            port=8100,
            session_token="short",
            timeout_s=10.0,
            max_request_bytes=1024,
        )
    with pytest.raises(ValueError, match="less than or equal to 536870912"):
        VerificationServiceSettings(
            provider=spec,
            host="127.0.0.1",
            port=8100,
            session_token="a" * 64,
            timeout_s=10.0,
            max_request_bytes=513 * 1024 * 1024,
        )


def test_agent_verification_config_matches_service_bounds():
    with pytest.raises(ValueError, match="less than or equal to 3600"):
        AgentVerificationConfig(timeout_s=3601)
    with pytest.raises(ValueError, match="serviceHost is invalid"):
        AgentVerificationConfig(service_host="not a host")
    with pytest.raises(ValueError, match="Extra inputs"):
        AgentVerificationConfig.model_validate({"unknownVerificationSetting": True})


def test_child_service_settings_reject_unknown_fields():
    with pytest.raises(ValueError, match="Extra inputs"):
        VerificationServiceSettings.model_validate(
            {
                "provider": _custom_spec(),
                "host": "127.0.0.1",
                "port": 8100,
                "session_token": "a" * 64,
                "timeout_s": 10.0,
                "max_request_bytes": 1024,
                "untrusted_override": True,
            }
        )


def test_process_constructor_rejects_unknown_provider_before_subprocess():
    engine = VerificationEngine(provider=object(), model="fixture", timeout_s=1.0)
    with pytest.raises(ValueError, match="unknown verification provider"):
        VerificationServiceProcess(
            engine=engine,
            host="127.0.0.1",
            port=8100,
            session_secret="secret",
            provider_spec=_custom_spec(provider_name="typo-provider"),
        )


def test_process_constructor_rejects_invalid_runtime_bounds_before_subprocess():
    engine = VerificationEngine(provider=object(), model="fixture", timeout_s=1.0)
    with pytest.raises(ValueError, match="startup timeout"):
        VerificationServiceProcess(
            engine=engine,
            host="127.0.0.1",
            port=8100,
            session_secret="secret",
            provider_spec=_custom_spec(),
            startup_timeout_s=0,
        )
    with pytest.raises(ValueError, match="request size"):
        VerificationServiceProcess(
            engine=engine,
            host="127.0.0.1",
            port=8100,
            session_secret="secret",
            provider_spec=_custom_spec(),
            max_request_bytes=512,
        )


@pytest.mark.parametrize("value", [512, 513 * 1024 * 1024, 1024.5, True])
def test_direct_handler_rejects_invalid_request_size_instead_of_clamping(value):
    from PhyAgentOS.verification.service import _handler

    engine = VerificationEngine(provider=object(), model="fixture", timeout_s=1.0)
    with pytest.raises(ValueError, match="request size"):
        _handler(engine, "a" * 64, max_request_bytes=value)


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("host", 127001, "host must be a string"),
        ("port", 8100.5, "port must be an integer"),
        ("port", True, "port must be an integer"),
        ("session_secret", 123, "session_secret is required"),
        ("startup_timeout_s", True, "startup timeout must be numeric"),
        ("max_request_bytes", 1024.5, "request size must be an integer"),
    ],
)
def test_process_constructor_rejects_implicitly_coercible_types(
    field, value, match
):
    engine = VerificationEngine(provider=object(), model="fixture", timeout_s=1.0)
    kwargs = {
        "engine": engine,
        "host": "127.0.0.1",
        "port": 8100,
        "session_secret": "secret",
        "provider_spec": _custom_spec(),
    }
    kwargs[field] = value
    with pytest.raises(ValueError, match=match):
        VerificationServiceProcess(**kwargs)
