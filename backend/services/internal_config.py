import os

from .translation import TranslationResult, TranslationServiceError, translate_text


DEFAULT_INTERNAL_LANGUAGES = "bn:Bengali,ar:Arabic,hi:Hindi,es:Spanish,fr:French,de:German,en:English"


def internal_translation_provider() -> str:
    return os.getenv("INTERNAL_TRANSLATION_PROVIDER", "nllb").strip().lower() or "nllb"


def allow_internal_demo_translation() -> bool:
    return os.getenv("ALLOW_INTERNAL_DEMO_TRANSLATION", "false").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def supported_internal_languages() -> list[dict]:
    raw_value = os.getenv("INTERNAL_SUPPORTED_LANGUAGES", DEFAULT_INTERNAL_LANGUAGES)
    languages = []
    for item in raw_value.split(","):
        code, _, name = item.strip().partition(":")
        code = code.strip()
        name = name.strip() or code.upper()
        if code:
            languages.append({"code": code, "name": name})
    return languages


def supported_language_codes() -> set[str]:
    return {item["code"] for item in supported_internal_languages()}


def validate_internal_language(code: str, field_name: str = "language") -> str:
    normalized = (code or "").strip().lower()
    if normalized not in supported_language_codes():
        raise TranslationServiceError(f"Unsupported {field_name}: {code}")
    return normalized


def internal_translate_text(
    text: str,
    source_language: str,
    target_language: str,
) -> TranslationResult:
    provider = internal_translation_provider()
    if provider == "demo" and not allow_internal_demo_translation():
        raise TranslationServiceError(
            "Internal demo translation is disabled. Configure NLLB_TRANSLATION_URL "
            "or set ALLOW_INTERNAL_DEMO_TRANSLATION=true for development only."
        )
    return translate_text(text, source_language, target_language, provider=provider)


def internal_provider_health() -> dict:
    provider = internal_translation_provider()

    if provider == "nllb":
        model_path = os.getenv("NLLB_TRANSLATION_MODEL", "").strip()
        if not model_path:
            return {
                "ok": False,
                "provider": provider,
                "configured": False,
                "message": "NLLB_TRANSLATION_MODEL path is not configured.",
            }
        if not os.path.exists(model_path):
            return {
                "ok": False,
                "provider": provider,
                "configured": False,
                "message": f"NLLB model folder not found at: {model_path}",
            }
        return {
            "ok": True,
            "provider": provider,
            "configured": True,
            "message": f"NLLB model found at: {model_path}",
        }

    if provider == "demo" and not allow_internal_demo_translation():
        return {
            "ok": False,
            "provider": provider,
            "configured": False,
            "message": "Internal demo translation is disabled.",
        }

    return {
        "ok": True,
        "provider": provider,
        "configured": True,
        "message": "Provider selected for internal translation.",
    }