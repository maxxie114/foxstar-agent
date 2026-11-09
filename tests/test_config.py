from foxstar_bot.config import load_config


def test_load_config_reads_reply_timing(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "reply_timing:",
                "  min_delay_seconds: 2.0",
                "  max_delay_seconds: 5.0",
                "  between_messages_seconds: 0.8",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(str(config_path))

    assert config.reply_timing.min_delay_seconds == 2.0
    assert config.reply_timing.max_delay_seconds == 5.0
    assert config.reply_timing.between_messages_seconds == 0.8


def test_load_config_reads_native_image_analysis_mode(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "model:\n  image_analysis_mode: native\n",
        encoding="utf-8",
    )

    config = load_config(str(config_path))

    assert config.model.image_analysis_mode == "native"


def test_load_config_falls_back_for_invalid_image_analysis_mode(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "model:\n  image_analysis_mode: surprise\n",
        encoding="utf-8",
    )

    config = load_config(str(config_path))

    assert config.model.image_analysis_mode == "tool"


def test_load_config_reads_sambanova_key_from_env(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("", encoding="utf-8")
    monkeypatch.setenv("SAMBA_NOVA_KEY", "test-samba-key")

    config = load_config(str(config_path))

    assert config.sambanova_api_key == "test-samba-key"


def test_load_config_prefers_minimax_token_key(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("", encoding="utf-8")
    monkeypatch.setenv("MINIMAX_TOKEN_KEY", "test-token-key")
    monkeypatch.setenv("MINIMAX_API_KEY", "test-payg-key")

    config = load_config(str(config_path))

    assert config.minimax_api_key == "test-token-key"


def test_load_config_uses_minimax_api_key_when_token_key_missing(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("", encoding="utf-8")
    monkeypatch.setenv("MINIMAX_TOKEN_KEY", "")
    monkeypatch.setenv("MINIMAX_API_KEY", "test-payg-key")

    config = load_config(str(config_path))

    assert config.minimax_api_key == "test-payg-key"


def test_load_config_reads_bedrock_key_fallback(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("", encoding="utf-8")
    monkeypatch.delenv("BEDROCK_API_KEY", raising=False)
    monkeypatch.setenv("BEDROCK_KEY_1", "test-bedrock-key")

    config = load_config(str(config_path))

    assert config.bedrock_api_key == "test-bedrock-key"


def test_load_config_reads_additional_provider_keys_and_urls(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("", encoding="utf-8")
    monkeypatch.setenv("ZAI_API_KEY", "zai-key")
    monkeypatch.setenv("ZAI_BASE_URL", "https://zai.example/v4")
    monkeypatch.setenv("TELNYX_API_KEY", "telnyx-key")
    monkeypatch.setenv("KIMI_API_KEY", "kimi-key")
    monkeypatch.setenv("KIMI_BASE_URL", "https://api.moonshot.cn/v1")

    config = load_config(str(config_path))

    assert config.zai_api_key == "zai-key"
    assert config.zai_base_url == "https://zai.example/v4"
    assert config.telnyx_api_key == "telnyx-key"
    assert config.telnyx_base_url == "https://api.telnyx.com/v2/ai/openai"
    assert config.kimi_api_key == "kimi-key"
    assert config.kimi_base_url == "https://api.moonshot.cn/v1"


def test_load_config_accepts_moonshot_key_alias(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("", encoding="utf-8")
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.setenv("MOONSHOT_API_KEY", "moonshot-key")

    config = load_config(str(config_path))

    assert config.kimi_api_key == "moonshot-key"


def test_load_config_reads_model_router(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "model_router:",
                "  enabled: true",
                "  low:",
                "    provider: sambanova",
                "    model: MiniMax-M2.5",
                "    reasoning_effort: low",
                "  medium:",
                "    provider: openrouter",
                "    model: z-ai/glm-5-turbo",
                "    reasoning_effort: medium",
                "  high:",
                "    provider: openai",
                "    model: gpt-5.4",
                "    reasoning_effort: high",
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(str(config_path))

    assert config.model_router.enabled is True
    assert config.model_router.low.provider == "sambanova"
    assert config.model_router.medium.model == "z-ai/glm-5-turbo"
    assert config.model_router.high.model == "gpt-5.4"
