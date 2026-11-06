import json
import pytest

from config import settings
from services.legal_documents import FIELDS, profile_status, render


def configure_legal(monkeypatch):
    values = {
        "LEGAL_OPERATOR_NAME": "测试运营者",
        "LEGAL_CONTACT_EMAIL": "privacy@example.test",
        "LEGAL_CONTACT_ADDRESS": "测试地址",
        "LEGAL_EFFECTIVE_DATE": "2026-11-05",
        "LEGAL_STORAGE_DESCRIPTION": "数据存于中国境内的测试环境。",
        "LEGAL_RETENTION_DESCRIPTION": "测试环境按已告知的账号、项目、日志及备份期限处理。",
        "LEGAL_ACCOUNT_DELETION_DESCRIPTION": "通过隐私联系邮箱提交申请，核验身份后依法处理并答复。",
        "LEGAL_AI_MARKING_DESCRIPTION": "发布前核查标识，具体制作和导出规则按服务内说明执行。",
        "LEGAL_THIRD_PARTIES_JSON": json.dumps([{
            "name": "测试服务商", "purpose": "登录与存储", "data": "账号标识和创作素材",
            "contact": "https://example.test/contact", "privacy_url": "https://example.test/privacy",
            "location": "中国境内",
        }]),
    }
    for key, value in values.items():
        monkeypatch.setattr(settings, key, value)


@pytest.mark.parametrize("kind", ["terms", "privacy"])
@pytest.mark.parametrize("provider", ["password", "qiling"])
def test_legal_document_uses_operator_data_and_selected_login_flow(monkeypatch, kind, provider):
    configure_legal(monkeypatch)
    monkeypatch.setattr(settings, "AUTH_PROVIDER", provider)
    html = render(kind)
    assert "测试运营者" in html and "privacy@example.test" in html
    assert "【填写" not in html and "草案" not in html
    if provider == "password":
        assert "密码" in html and "器灵" not in html
    else:
        assert "器灵" in html and "密码哈希" not in html
    if kind == "privacy":
        assert "测试服务商" in html and "https://example.test/privacy" in html
        assert 'id="account-data-requests"' in html


def test_missing_configuration_is_explicit_and_does_not_publish_placeholders(monkeypatch):
    for variable in FIELDS.values():
        monkeypatch.setattr(settings, variable, "")
    profile, missing = profile_status()
    assert profile is None
    assert set(missing) == set(FIELDS.values())


def test_document_escapes_operator_input_and_rejects_script_urls(monkeypatch):
    configure_legal(monkeypatch)
    monkeypatch.setattr(settings, "LEGAL_OPERATOR_NAME", '<script>alert("bad")</script>')
    assert "<script>" not in render("privacy")
    entries = json.loads(settings.LEGAL_THIRD_PARTIES_JSON)
    entries[0]["privacy_url"] = "javascript:alert(1)"
    monkeypatch.setattr(settings, "LEGAL_THIRD_PARTIES_JSON", json.dumps(entries))
    assert profile_status() == (None, ["LEGAL_THIRD_PARTIES_JSON"])


def test_invalid_effective_date_is_rejected(monkeypatch):
    configure_legal(monkeypatch)
    monkeypatch.setattr(settings, "LEGAL_EFFECTIVE_DATE", "not-a-date")
    assert profile_status() == (None, ["LEGAL_EFFECTIVE_DATE"])
