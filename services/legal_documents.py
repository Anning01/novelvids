"""Public service notices rendered from deployment-owned information."""

import json
from datetime import date
from html import escape
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from config import settings


class ThirdParty(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    data: str = Field(min_length=1)
    contact: str = Field(min_length=1)
    privacy_url: str
    location: str = Field(min_length=1)

    @field_validator("privacy_url")
    @classmethod
    def public_https_url(cls, value: str) -> str:
        from urllib.parse import urlsplit
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Expected a public HTTPS privacy policy URL")
        return value


class LegalProfile(BaseModel):
    operator: str = Field(min_length=1)
    email: str = Field(pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    address: str = Field(min_length=1)
    effective: date
    storage: str = Field(min_length=1)
    retention: str = Field(min_length=1)
    deletion: str = Field(min_length=1)
    ai_marking: str = Field(min_length=1)
    third_parties: list[ThirdParty]


FIELDS = {
    "operator": "LEGAL_OPERATOR_NAME",
    "email": "LEGAL_CONTACT_EMAIL",
    "address": "LEGAL_CONTACT_ADDRESS",
    "effective": "LEGAL_EFFECTIVE_DATE",
    "storage": "LEGAL_STORAGE_DESCRIPTION",
    "retention": "LEGAL_RETENTION_DESCRIPTION",
    "deletion": "LEGAL_ACCOUNT_DELETION_DESCRIPTION",
    "ai_marking": "LEGAL_AI_MARKING_DESCRIPTION",
    "third_parties": "LEGAL_THIRD_PARTIES_JSON",
}


def profile_status() -> tuple[LegalProfile | None, list[str]]:
    data = {field: getattr(settings, variable) for field, variable in FIELDS.items()}
    try:
        data["third_parties"] = json.loads(data["third_parties"])
    except (ValueError, TypeError):
        return None, ["LEGAL_THIRD_PARTIES_JSON"] + [
            variable for field, variable in FIELDS.items() if field != "third_parties" and not data[field]
        ]
    try:
        profile = LegalProfile.model_validate(data)
    except ValidationError as error:
        return None, sorted({FIELDS[item["loc"][0]] for item in error.errors()})
    if settings.AUTH_PROVIDER == "qiling" and not profile.third_parties:
        return None, ["LEGAL_THIRD_PARTIES_JSON"]
    return profile, []


def require_profile() -> LegalProfile:
    profile, _ = profile_status()
    if profile is None:
        raise HTTPException(503, "服务协议信息尚未配置完整，请联系运营者")
    return profile


def sections(kind: Literal["terms", "privacy"], profile: LegalProfile) -> list[tuple[str, list[str]]]:
    contact = f"运营者为{profile.operator}。联系邮箱为{profile.email}，联系地址为{profile.address}。"
    sign_in = (
        "你通过器灵完成微信授权后，猫影向器灵核验账号，使用器灵账号标识建立账号关联，并取得昵称用于建立账号。猫影使用自己的会话凭证维持登录和校验权限。"
        if settings.AUTH_PROVIDER == "qiling" else
        "你通过本部署的账号密码登录。我们保存用户名、昵称和不可逆的密码哈希，使用会话凭证维持登录及校验权限。获邀用户可以使用邀请链接注册并加入团队。"
    )
    if kind == "terms":
        return [
            ("服务提供者与适用范围", [contact, "猫影短剧提供故事与剧本创作、角色资产管理、分镜设计、AI 图片与视频生成、视频复刻、编辑及成片管理。本协议适用于本运营者提供的在线服务。开源代码的使用、修改及再分发适用代码仓库附带的开源许可证。"]),
            ("账号与团队协作", [sign_in, "请妥善保管登录凭证。注册时系统为账号创建一个个人团队。加入其他团队须使用邀请链接。项目归创建时选定的团队，成员按角色访问团队项目。团队管理员可以调整成员权限，请在加入前了解团队的协作安排。"]),
            ("素材授权与作品使用", ["你应对上传或输入的文本、提示词、图片、视频、声音等材料拥有相应权利或必要授权。涉及他人肖像、声音、隐私、商业秘密等时，应取得适当授权。为执行你请求的操作，运营者可在提供服务所需范围内保存、转换和传输相关材料，你原有的素材权利不因使用本服务而转移。", "生成结果可能存在错误、遗漏或相似内容。发布或商用前，请核对内容、素材授权和所选模型的使用条件。作品的权利归属依法确定，运营者不承诺所有生成结果均构成可独占的作品。"]),
            ("生成合成内容标识", [profile.ai_marking, "对外发布 AI 生成合成内容时，请遵守适用的标识要求和发布平台规则，主动声明生成合成情况，保留依法添加的显式及隐式标识。运营者承担其依法应履行的标识义务，用户的声明义务不替代该责任。"]),
            ("行为规范与费用", ["不得利用本服务违法发布内容、侵害他人权益、实施欺诈或绕过访问控制。运营者可以依法对违规内容和账号采取适当措施，你可通过联系邮箱提出说明或申诉。", "如功能收费，以执行前展示的计费规则、所选模型和团队费用归属为准。请核对任务和费用信息后再提交。费用异议、服务中断造成的损失及退款请求，按实际履约情况、适用规则和法律处理。"]),
            ("服务变更、退出与争议", [profile.deletion, "服务或协议发生影响你权益的重要变化时，运营者将以服务内通知等适当方式说明。对你的法定权利，本协议不作排除或不当限制。双方可先协商处理争议，无法协商的，依法向有管辖权的人民法院解决。"]),
        ]
    return [
        ("处理者与联系方式", [contact, "本政策说明本部署收集和使用个人信息的方式。你可以通过上述邮箱申请查阅、复制、更正、补充、删除个人信息，提出注销账号或撤回同意的请求。"]),
        ("信息范围与处理目的", [sign_in, "团队身份、成员角色、项目及任务状态用于协作和访问控制。你输入或上传的故事、提示词、参考图片、音频、视频、分镜与生成结果用于保存项目并完成你请求的操作。任务用量和费用记录用于显示进度、核对团队消费和处理费用异议。请求 IP、访问时间及必要的安全日志用于防范异常访问和排查故障，保存规则见下文。", "请在提供涉及他人的人脸、声音、身份、联系方式或私密资料前确认相应授权。法律要求单独同意或特别保护的处理，将另行告知并依法处理。"]),
        ("第三方服务与团队可见范围", ["第三方服务的名称、目的、涉及数据、联系方式、隐私政策和处理地点列于下方清单。提交模型生成任务时，所需的提示词和参考素材会发给你或团队选定的模型服务。与第三方独立约定的用途和权限，以该次告知及相应协议为准，依法需单独同意的处理将另行征求。", "团队资料按成员角色提供访问。通过发布或分享公开的作品，可能被公开范围内的人查看或传播。请在发布前核对权限和内容。"]),
        ("浏览器存储", ["浏览器本地存储用于保存猫影会话令牌、当前团队以及界面偏好。退出登录会清理本机的登录凭证。你可通过浏览器设置管理本地存储，清理可能使登录状态和部分界面偏好失效。"]),
        ("存储地点、期限与保护", [profile.storage, profile.retention, "运营者依据处理目的采取访问权限、凭证保护及必要的备份等安全措施，超出适用期限的信息依法删除或匿名化。依法必须保留的记录，仅在相应范围内处理。"]),
        ("权利申请、注销与未成年人", [profile.deletion, "收到请求后，我们会通过必要的身份核验确认申请人身份，并依法答复。撤回同意不影响撤回前基于同意进行处理的效力。对共用团队资料和依法须保留的账务记录，依法说明并处理。", "未成年人应在监护人指导下使用服务。涉及不满十四周岁未成年人个人信息的，依法征得监护人同意并采取相应保护措施。"]),
        ("政策更新", ["处理目的、方式、信息种类或其他重要事项发生变化时，运营者将及时在服务内通知。依法需重新取得同意的，将另行征求。"]),
    ]


def render(kind: Literal["terms", "privacy"]) -> str:
    profile = require_profile()
    title = "用户协议" if kind == "terms" else "隐私政策"
    blocks = []
    for heading, paragraphs in sections(kind, profile):
        section_id = ' id="account-data-requests"' if kind == "privacy" and heading == "处理者与联系方式" else ""
        blocks.append(f"<section{section_id}><h2>{escape(heading)}</h2>" + "".join(
            f"<p>{escape(paragraph)}</p>" for paragraph in paragraphs
        ) + "</section>")
    if kind == "privacy":
        blocks.append("<section><h2>第三方服务清单</h2>")
        for item in profile.third_parties:
            blocks.append(f"<h3>{escape(item.name)}</h3><dl>" + "".join(
                f"<dt>{label}</dt><dd>{escape(value)}</dd>" for label, value in [
                    ("处理目的", item.purpose), ("涉及信息", item.data), ("联系方式", item.contact), ("处理地点", item.location),
                ]
            ) + f'<dt>隐私政策</dt><dd><a href="{escape(item.privacy_url, quote=True)}">{escape(item.privacy_url)}</a></dd></dl>')
        if not profile.third_parties:
            blocks.append("<p>本部署未登记外部数据接收方。如后续配置第三方模型、存储或其他服务，运营者需在启用前更新清单并依法告知。</p>")
        blocks.append("</section>")
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>猫影短剧 · {title}</title>
<style>
:root{{color-scheme:light dark;font-family:system-ui,sans-serif;line-height:1.8}}
body{{margin:0}}main{{max-width:760px;margin:40px auto 64px;padding:0 22px}}
h1{{line-height:1.3}}h2{{font-size:1.25rem;margin-top:30px}}
p,dd{{white-space:pre-line;overflow-wrap:anywhere}}dd{{margin:0 0 10px}}
dt{{font-weight:650}}a{{color:light-dark(#514294,#cdbaff)}}a:focus-visible{{outline:2px solid currentColor}}
</style></head><body><main><h1>猫影短剧 · {title}</h1><p>生效日期 {profile.effective.isoformat()}</p>
{''.join(blocks)}</main></body></html>"""
