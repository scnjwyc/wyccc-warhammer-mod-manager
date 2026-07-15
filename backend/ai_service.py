from __future__ import annotations

import json
import re
from typing import Any
from urllib import error, request
from urllib.parse import urlparse

from .app_settings import DEFAULT_LANGUAGE
from .models import ModAsset
from .warhammer_translation import build_mod_translation_prompts


_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def _chat_completions_url(base_url: str) -> str:
    normalized = str(base_url or "").strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("AI Base URL 必须是有效的 http 或 https 地址")
    if normalized.casefold().endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def _response_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("AI 返回中缺少 choices")
    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            str(item.get("text") or "")
            for item in content
            if isinstance(item, dict) and item.get("text")
        ]
        return "".join(parts)
    raise ValueError("AI 返回中缺少文本内容")


def _parse_generated_fields(text: str) -> dict[str, str]:
    cleaned = _JSON_FENCE_RE.sub("", str(text or "").strip()).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("AI 未返回可识别的 JSON")
    try:
        payload = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError("AI 返回的 JSON 格式无效") from exc
    if not isinstance(payload, dict):
        raise ValueError("AI 返回格式必须是对象")
    alias = str(
        payload.get("title") or payload.get("alias") or payload.get("alias_name") or ""
    ).strip()[:120]
    notes = str(payload.get("description") or payload.get("notes") or "").strip()[:2000]
    if not alias and not notes:
        raise ValueError("AI 没有生成标题或备注")
    return {"alias": alias, "notes": notes}


def generate_mod_user_data(asset: ModAsset, settings: dict[str, Any]) -> dict[str, str]:
    if not settings.get("ai_enabled"):
        raise ValueError("AI 功能未启用，请先在设置中完成 AI 配置")
    model = str(settings.get("ai_model") or "").strip()
    if not model:
        raise ValueError("尚未设置 AI 模型名称")
    endpoint = _chat_completions_url(str(settings.get("ai_base_url") or ""))
    api_key = str(settings.get("ai_api_key") or "").strip()

    system_prompt, user_prompt = build_mod_translation_prompts(
        asset,
        str(settings.get("ai_glossary_path") or ""),
        str(settings.get("language") or DEFAULT_LANGUAGE),
    )
    body = {
        "model": model,
        "temperature": float(settings.get("ai_temperature", 0.3)),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    http_request = request.Request(
        endpoint,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with request.urlopen(http_request, timeout=60) as response:
            response_payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except error.HTTPError as exc:
        detail = exc.read(2048).decode("utf-8", errors="replace")
        try:
            error_payload = json.loads(detail)
            detail = str(error_payload.get("error", {}).get("message") or detail)
        except (AttributeError, json.JSONDecodeError, TypeError):
            pass
        raise ValueError(f"AI 请求失败（HTTP {exc.code}）：{detail[:300]}") from exc
    except error.URLError as exc:
        raise ValueError(f"无法连接 AI 服务：{exc.reason}") from exc
    except (OSError, TimeoutError) as exc:
        raise ValueError(f"AI 请求失败：{exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError("AI 服务返回的不是有效 JSON") from exc

    if not isinstance(response_payload, dict):
        raise ValueError("AI 服务返回格式无效")
    return _parse_generated_fields(_response_text(response_payload))
