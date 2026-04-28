from __future__ import annotations

import json
import os
import uuid
from typing import Any
from urllib import error, request

from ..ai_generation import AiApiError
from .schemas import RawPresentation

SYSTEM_PROMPT = (
    "Ты — конвертер PPTX в JSON-шаблон презентации.\n\n"
    "Задача:\n"
    "преобразовать входные данные слайдов в строгую JSON-схему.\n\n"
    "Правила:\n"
    "1. Поля корневого объекта: schemaVersion, documentType, id, name, slideSize, theme, layouts.\n"
    "2. slideSize: widthEmu, heightEmu, ratio.\n"
    "3. theme: fonts.heading, fonts.body, colors.background, colors.text, colors.primary, colors.secondary, colors.accent.\n"
    "4. slideType: title, text, bullets, image, conclusion.\n"
    "5. Элементы: title, subtitle, body, bulletList, image.\n"
    "6. element.type должен быть text или image, element.role должен быть одним из title, subtitle, body, bulletList, image.\n"
    "7. Для текстовых элементов используйте интервал Inter, цвет текста #111827, фон #FFFFFF, primary #2563EB, secondary #64748B, accent #F97316.\n"
    "8. Установите constraints.maxLines, constraints.maxChars, constraints.overflow=\"shrink\" для длинных блоков.\n"
    "9. Используйте только чистый JSON без комментариев, Markdown и лишнего текста вокруг JSON.\n"
    "10. Не теряйте текст, сохраняйте переносы строк.\n"
)


def normalize_with_qwen(raw_data: dict[str, Any], max_new_tokens: int = 2048) -> dict[str, Any]:
    RawPresentation.model_validate(raw_data)
    token = os.getenv("RT_AI_TOKEN")
    if not token:
        raise AiApiError(401, "RT_AI_TOKEN is not configured")

    base_url = os.getenv("RT_AI_BASE_URL", "https://ai.rt.ru/api/1.0").rstrip("/")
    model = os.getenv("RT_AI_LLM_MODEL", "Qwen/Qwen2.5-72B-Instruct")
    timeout = float(os.getenv("RT_AI_TIMEOUT_SECONDS", "90"))

    user_message = (
        "Сгенерируй JSON-шаблон презентации на основе raw PPTX-данных."
        " Данные входного файла размещены после этого текста.\n\n"
        f"Входной JSON:\n{json.dumps(raw_data, ensure_ascii=False)}"
    )

    body = {
        "uuid": str(uuid.uuid4()),
        "chat": {
            "model": model,
            "user_message": user_message,
            "contents": [{"type": "text", "text": user_message}],
            "message_template": "<s>{role}\n{content}</s>",
            "response_template": "<s>bot\n",
            "system_prompt": SYSTEM_PROMPT,
            "max_new_tokens": max_new_tokens,
            "no_repeat_ngram_size": 15,
            "repetition_penalty": 1.1,
            "temperature": 0.2,
            "top_k": 40,
            "top_p": 0.9,
            "chat_history": [],
        },
    }

    data = _request_json(f"{base_url}/llama/chat", "POST", token, json.dumps(body, ensure_ascii=False).encode("utf-8"), timeout)
    content = _extract_response_content(data)
    parsed = _extract_json(content)
    if not isinstance(parsed, dict):
        raise AiApiError(502, "Qwen response must be a JSON object")
    return parsed


def _request_json(url: str, method: str, token: str, data: bytes | None, timeout: float) -> Any:
    req = request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = _read_http_error(exc)
        if exc.code in {401, 403}:
            raise AiApiError(401, f"External AI service rejected RT_AI_TOKEN: {detail}") from exc
        raise AiApiError(502, f"External AI service returned HTTP {exc.code}: {detail}") from exc
    except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise AiApiError(502, f"External AI service request failed: {exc}") from exc


def _read_http_error(exc: error.HTTPError) -> str:
    try:
        return exc.read(2000).decode("utf-8", "replace").strip() or exc.reason or "empty response body"
    except Exception:
        return exc.reason or "empty response body"


def _extract_response_content(data: Any) -> str:
    try:
        return data[0]["message"]["content"]
    except (TypeError, IndexError, KeyError) as exc:
        raise AiApiError(502, "Qwen response does not contain message.content") from exc


def _extract_json(text: str) -> dict[str, Any] | list[Any]:
    if not isinstance(text, str):
        raise AiApiError(502, "Qwen response content is not text")

    trimmed = text.strip()
    try:
        parsed = json.loads(trimmed)
        return parsed
    except json.JSONDecodeError:
        pass

    if trimmed.startswith("```"):
        cleaned = trimmed.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

    for start, end in (("{", "}"), ("[", "]")):
        first = trimmed.find(start)
        last = trimmed.rfind(end)
        if first >= 0 and last > first:
            fragment = trimmed[first : last + 1]
            try:
                return json.loads(fragment)
            except json.JSONDecodeError:
                continue

    raise AiApiError(502, "Qwen response is not valid JSON")
