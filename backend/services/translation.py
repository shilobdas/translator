from dataclasses import dataclass
import os
import time
import requests
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
import torch


class TranslationServiceError(Exception):
    pass


@dataclass
class TranslationResult:
    text: str
    provider: str
    demo_mode: bool
    model: str | None = None
    usage_tokens: int | None = None


PROVIDER_LABELS = {
    "demo": "Demo",
    "nllb": "NLLB",
    "openai": "OpenAI",
    "gemini": "Gemini",
    "libretranslate": "LibreTranslate",
}

DEFAULT_MODELS = {
    "nllb": "nllb-200",
    "openai": "gpt-4.1-mini",
    "gemini": "gemini-3.5-flash",
}

# --------------------------------------------------------------------------- #
# NLLB — language code map + model cache                                       #
# --------------------------------------------------------------------------- #

_NLLB_LANG_MAP = {
    "en": "eng_Latn",
    "bn": "ben_Beng",
    "ar": "arb_Arab",
    "hi": "hin_Deva",
    "es": "spa_Latn",
    "fr": "fra_Latn",
    "de": "deu_Latn",
    "zh": "zho_Hans",
    "ru": "rus_Cyrl",
    "pt": "por_Latn",
    "ja": "jpn_Jpan",
    "ko": "kor_Hang",
}

# Loaded once on first translation request, reused for all subsequent ones
_nllb_tokenizer = None
_nllb_model = None


def _to_nllb_lang(lang: str) -> str:
    """Convert a short language code (e.g. 'bn') to NLLB format (e.g. 'ben_Beng')."""
    lang = lang.strip()
    if "_" in lang:
        return lang  # already in NLLB format
    return _NLLB_LANG_MAP.get(lang.lower(), lang)


def _get_nllb_model():
    """Load NLLB tokenizer + model from local path once and cache in memory."""
    global _nllb_tokenizer, _nllb_model

    if _nllb_tokenizer is not None and _nllb_model is not None:
        return _nllb_tokenizer, _nllb_model

    model_path = os.getenv("NLLB_TRANSLATION_MODEL", "").strip()
    if not model_path:
        raise TranslationServiceError(
            "NLLB_TRANSLATION_MODEL is required when translation provider is nllb. "
            "Set it to the full path of your local model folder."
        )

    try:
        _nllb_tokenizer = AutoTokenizer.from_pretrained(model_path)
        _nllb_model = AutoModelForSeq2SeqLM.from_pretrained(model_path)
        _nllb_model.eval()
        if torch.cuda.is_available():
            _nllb_model = _nllb_model.to("cuda")
    except Exception as exc:
        raise TranslationServiceError(f"Failed to load NLLB model from '{model_path}': {exc}") from exc

    return _nllb_tokenizer, _nllb_model


# --------------------------------------------------------------------------- #
# Provider helpers                                                              #
# --------------------------------------------------------------------------- #

def normalize_provider(provider: str | None = None) -> str:
    value = provider
    if value is None:
        value = os.getenv("TRANSLATION_PROVIDER", "demo")
    normalized = value.strip().lower()
    return normalized or "demo"


def get_provider_model(provider: str, model: str | None = None) -> str | None:
    explicit_model = (model or "").strip()
    if explicit_model:
        return explicit_model
    if provider == "nllb":
        return (os.getenv("NLLB_TRANSLATION_MODEL") or DEFAULT_MODELS[provider]).strip()
    if provider == "openai":
        return (os.getenv("OPENAI_TRANSLATION_MODEL") or DEFAULT_MODELS[provider]).strip()
    if provider == "gemini":
        return (os.getenv("GEMINI_TRANSLATION_MODEL") or DEFAULT_MODELS[provider]).strip()
    return None


def available_translation_providers() -> list[dict]:
    selected_provider = normalize_provider()
    nllb_model = os.getenv("NLLB_TRANSLATION_MODEL", "").strip()
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    libre_url = os.getenv("LIBRETRANSLATE_URL", "").strip()

    configured = {
        "demo": True,
        "nllb": bool(nllb_model),   # configured when model path is set
        "openai": bool(openai_key),
        "gemini": bool(gemini_key),
        "libretranslate": bool(libre_url),
    }

    return [
        {
            "id": provider,
            "label": PROVIDER_LABELS[provider],
            "selected": provider == selected_provider,
            "configured": configured[provider],
            "demo_mode": provider == "demo",
            "default_model": get_provider_model(provider),
        }
        for provider in PROVIDER_LABELS
    ]


# --------------------------------------------------------------------------- #
# Main translation entry point                                                  #
# --------------------------------------------------------------------------- #

def translate_text(
    text: str,
    source_language: str,
    target_language: str,
    provider: str | None = None,
    model: str | None = None,
) -> TranslationResult:
    selected_provider = normalize_provider(provider)

    if selected_provider == "nllb":
        return _translate_with_nllb(text, source_language, target_language, model)

    if selected_provider == "openai":
        return _translate_with_openai(text, source_language, target_language, model)

    if selected_provider == "gemini":
        return _translate_with_gemini(text, source_language, target_language, model)

    if selected_provider == "libretranslate":
        return _translate_with_libretranslate(text, source_language, target_language)

    if selected_provider == "demo":
        return TranslationResult(
            text=f"[Demo translation: {text} ({source_language} -> {target_language})]",
            provider="demo",
            demo_mode=True,
        )

    raise TranslationServiceError(f"Unsupported translation provider: {selected_provider}")


# --------------------------------------------------------------------------- #
# NLLB — direct in-process translation (no separate server needed)             #
# --------------------------------------------------------------------------- #
_NLLB_LANG_MAP = {
    "en": "eng_Latn",
    "bn": "ben_Beng",
    "ar": "arb_Arab",
    "hi": "hin_Deva",
    "es": "spa_Latn",
    "fr": "fra_Latn",
    "de": "deu_Latn",
    "zh": "zho_Hans",
    "ru": "rus_Cyrl",
    "pt": "por_Latn",
    "ja": "jpn_Jpan",
    "ko": "kor_Hang",
}

_nllb_tokenizer = None
_nllb_model = None


def _to_nllb_lang(lang: str) -> str:
    """Convert a short language code (e.g. 'bn') to NLLB format (e.g. 'ben_Beng')."""
    lang = lang.strip()
    if "_" in lang:
        return lang
    return _NLLB_LANG_MAP.get(lang.lower(), lang)


def _get_nllb_model():
    """Load NLLB tokenizer + model from local path once and cache in memory."""
    global _nllb_tokenizer, _nllb_model

    if _nllb_tokenizer is not None and _nllb_model is not None:
        return _nllb_tokenizer, _nllb_model

    model_path = os.getenv("NLLB_TRANSLATION_MODEL", "").strip()
    if not model_path:
        raise TranslationServiceError(
            "NLLB_TRANSLATION_MODEL is required when translation provider is nllb. "
            "Set it to the full path of your local model folder."
        )

    try:
        _nllb_tokenizer = AutoTokenizer.from_pretrained(model_path)
        _nllb_model = AutoModelForSeq2SeqLM.from_pretrained(model_path)
        _nllb_model.eval()
        if torch.cuda.is_available():
            _nllb_model = _nllb_model.to("cuda")
    except Exception as exc:
        raise TranslationServiceError(
            f"Failed to load NLLB model from '{model_path}': {exc}"
        ) from exc

    return _nllb_tokenizer, _nllb_model


def _translate_with_nllb(
    text: str,
    source_language: str,
    target_language: str,
    model: str | None = None,
) -> TranslationResult:
    tokenizer, nllb_model = _get_nllb_model()

    src = _to_nllb_lang(source_language)
    tgt = _to_nllb_lang(target_language)

    def translate_chunk(chunk: str) -> str:
        inputs = tokenizer(
            chunk,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=512,
        )
        if torch.cuda.is_available():
            inputs = {k: v.to("cuda") for k, v in inputs.items()}

        target_lang_id = tokenizer.convert_tokens_to_ids(tgt)

        translated_tokens = nllb_model.generate(
            **inputs,
            forced_bos_token_id=target_lang_id,
            max_length=512,
        )
        return tokenizer.batch_decode(
            translated_tokens, skip_special_tokens=True
        )[0]

    def split_into_chunks(raw_text: str, max_tokens: int = 400) -> list[str]:
        """Split text into sentence-aware chunks that fit within token limit."""
        import re
        sentences = re.split(r'(?<=[।.!?])\s+', raw_text.strip())

        chunks = []
        current_chunk = []
        current_length = 0

        for sentence in sentences:
            sentence_tokens = len(sentence) // 4 + 1
            if current_length + sentence_tokens > max_tokens and current_chunk:
                chunks.append(" ".join(current_chunk))
                current_chunk = [sentence]
                current_length = sentence_tokens
            else:
                current_chunk.append(sentence)
                current_length += sentence_tokens

        if current_chunk:
            chunks.append(" ".join(current_chunk))

        return chunks

    try:
        estimated_tokens = len(text) // 4

        if estimated_tokens <= 400:
            translated_text = translate_chunk(text)
        else:
            chunks = split_into_chunks(text, max_tokens=400)
            translated_parts = [translate_chunk(chunk) for chunk in chunks]
            translated_text = " ".join(translated_parts)

    except Exception as exc:
        raise TranslationServiceError(f"NLLB translation failed: {exc}") from exc

    selected_model = get_provider_model("nllb", model)
    return TranslationResult(
        text=translated_text,
        provider="nllb",
        demo_mode=False,
        model=selected_model,
    )

# --------------------------------------------------------------------------- #
# OpenAI                                                                        #
# --------------------------------------------------------------------------- #

def _translation_instruction(source_language: str, target_language: str) -> str:
    return (
        f"Translate the user's content from {source_language} to {target_language}. "
        "Return only the translated content. Preserve HTML tags, Markdown, URLs, "
        "variables, placeholders, shortcodes, and line breaks exactly where possible."
    )


def _request_timeout() -> float:
    return float(os.getenv("TRANSLATION_TIMEOUT_SECONDS", "20"))


def _translate_with_openai(
    text: str,
    source_language: str,
    target_language: str,
    model: str | None = None,
) -> TranslationResult:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise TranslationServiceError(
            "OPENAI_API_KEY is required when translation provider is openai"
        )

    selected_model = get_provider_model("openai", model)
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
    payload = {
        "model": selected_model,
        "instructions": _translation_instruction(source_language, target_language),
        "input": text,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            f"{base_url}/responses",
            json=payload,
            headers=headers,
            timeout=_request_timeout(),
        )
    except requests.RequestException as exc:
        raise TranslationServiceError(f"OpenAI translation request failed: {exc}") from exc

    data = _parse_json_response(response, "OpenAI")
    translated_text = _extract_openai_text(data)
    if not translated_text:
        raise TranslationServiceError("OpenAI response did not include translated text")

    usage = data.get("usage") or {}
    usage_tokens = usage.get("total_tokens")
    return TranslationResult(
        text=translated_text,
        provider="openai",
        demo_mode=False,
        model=selected_model,
        usage_tokens=usage_tokens if isinstance(usage_tokens, int) else None,
    )


# --------------------------------------------------------------------------- #
# Gemini                                                                        #
# --------------------------------------------------------------------------- #

def _translate_with_gemini(
    text: str,
    source_language: str,
    target_language: str,
    model: str | None = None,
) -> TranslationResult:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise TranslationServiceError(
            "GEMINI_API_KEY is required when translation provider is gemini"
        )

    selected_model = get_provider_model("gemini", model)
    base_url = os.getenv(
        "GEMINI_BASE_URL",
        "https://generativelanguage.googleapis.com/v1beta",
    ).strip().rstrip("/")
    payload = {
        "system_instruction": {
            "parts": [{"text": _translation_instruction(source_language, target_language)}],
        },
        "contents": [{"parts": [{"text": text}]}],
    }
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }

    max_retries = 3
    delay_seconds = 2

    for attempt in range(max_retries):
        try:
            response = requests.post(
                f"{base_url}/models/{selected_model}:generateContent",
                json=payload,
                headers=headers,
                timeout=_request_timeout(),
            )
        except requests.RequestException as exc:
            raise TranslationServiceError(f"Gemini translation request failed: {exc}") from exc

        if response.status_code == 503 and attempt < max_retries - 1:
            time.sleep(delay_seconds)
            delay_seconds *= 2  # exponential backoff: 2s, 4s, 8s
            continue

        break

    data = _parse_json_response(response, "Gemini")
    translated_text = _extract_gemini_text(data)
    if not translated_text:
        raise TranslationServiceError("Gemini response did not include translated text")

    usage = data.get("usageMetadata") or {}
    usage_tokens = usage.get("totalTokenCount")
    return TranslationResult(
        text=translated_text,
        provider="gemini",
        demo_mode=False,
        model=selected_model,
        usage_tokens=usage_tokens if isinstance(usage_tokens, int) else None,
    )

# --------------------------------------------------------------------------- #
# LibreTranslate                                                                #
# --------------------------------------------------------------------------- #

def _translate_with_libretranslate(
    text: str,
    source_language: str,
    target_language: str,
) -> TranslationResult:
    base_url = os.getenv("LIBRETRANSLATE_URL", "").strip().rstrip("/")
    if not base_url:
        raise TranslationServiceError(
            "LIBRETRANSLATE_URL is required when TRANSLATION_PROVIDER=libretranslate"
        )

    payload = {
        "q": text,
        "source": source_language,
        "target": target_language,
        "format": "text",
    }

    api_key = os.getenv("LIBRETRANSLATE_API_KEY", "").strip()
    if api_key:
        payload["api_key"] = api_key

    try:
        response = requests.post(
            f"{base_url}/translate",
            json=payload,
            timeout=_request_timeout(),
        )
    except requests.RequestException as exc:
        raise TranslationServiceError(f"Translation provider request failed: {exc}") from exc

    data = _parse_json_response(response, "LibreTranslate")
    translated_text = data.get("translatedText")
    if not translated_text:
        raise TranslationServiceError("Translation provider response did not include translatedText")

    return TranslationResult(
        text=translated_text,
        provider="libretranslate",
        demo_mode=False,
    )


# --------------------------------------------------------------------------- #
# Shared response helpers                                                       #
# --------------------------------------------------------------------------- #

def _parse_json_response(response: requests.Response, provider_label: str) -> dict:
    if response.status_code >= 400:
        raise TranslationServiceError(
            f"{provider_label} returned {response.status_code}: {response.text}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise TranslationServiceError(f"{provider_label} returned invalid JSON") from exc

    if not isinstance(data, dict):
        raise TranslationServiceError(f"{provider_label} returned an unsupported response shape")
    return data


def _extract_first_text(data: dict, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    nested_data = data.get("data")
    if isinstance(nested_data, dict):
        return _extract_first_text(nested_data, keys)
    return None


def _extract_openai_text(data: dict) -> str | None:
    output_text = data.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    parts = []
    for item in data.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if isinstance(text, str):
                parts.append(text)

    translated = "".join(parts).strip()
    return translated or None


def _extract_gemini_text(data: dict) -> str | None:
    parts = []
    for candidate in data.get("candidates", []):
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content") or {}
        for part in content.get("parts", []):
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str):
                parts.append(text)
        if parts:
            break

    translated = "".join(parts).strip()
    return translated or None