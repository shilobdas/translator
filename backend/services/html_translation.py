import re

from bs4 import BeautifulSoup, Comment, NavigableString

from .translation import TranslationResult, translate_text


SKIP_PARENT_TAGS = {"script", "style", "code", "pre", "textarea"}
SHORTCODE_PATTERN = re.compile(r"(\[[^\[\]]+\])")


def translate_html(
    html: str,
    source_language: str,
    target_language: str,
    provider: str | None = None,
    model: str | None = None,
) -> TranslationResult:
    soup = BeautifulSoup(html or "", "html.parser")
    result_provider = "demo"
    demo_mode = True
    selected_model = None
    usage_tokens = 0

    for node in list(soup.find_all(string=True)):
        if isinstance(node, Comment):
            continue
        if node.parent and node.parent.name in SKIP_PARENT_TAGS:
            continue
        if not str(node).strip():
            continue

        translated_parts = []
        for part in SHORTCODE_PATTERN.split(str(node)):
            if not part:
                continue
            if SHORTCODE_PATTERN.fullmatch(part) or not part.strip():
                translated_parts.append(part)
                continue
            result = translate_text(part, source_language, target_language, provider, model)
            translated_parts.append(result.text)
            result_provider = result.provider
            demo_mode = result.demo_mode
            selected_model = result.model
            usage_tokens += result.usage_tokens or 0

        node.replace_with(NavigableString("".join(translated_parts)))

    return TranslationResult(
        text=str(soup),
        provider=result_provider,
        demo_mode=demo_mode,
        model=selected_model,
        usage_tokens=usage_tokens or None,
    )
