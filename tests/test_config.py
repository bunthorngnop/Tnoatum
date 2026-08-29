from pathlib import Path

import pytest

from tnoat_tum_cafe.config import load_settings


def test_defaults_are_phnom_penh_and_separate_currencies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("SHOP_TIMEZONE", "SUPPORTED_CURRENCIES", "OWNER_TELEGRAM_IDS"):
        monkeypatch.delenv(name, raising=False)
    settings = load_settings(tmp_path / "missing.env")
    assert settings.timezone_name == "Asia/Phnom_Penh"
    assert settings.supported_currencies == ("KHR", "USD")
    assert settings.owner_telegram_ids == ()


def test_owner_ids_must_be_numeric(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OWNER_TELEGRAM_IDS", "owner-name")
    with pytest.raises(ValueError, match="numeric IDs"):
        load_settings(tmp_path / "missing.env")

