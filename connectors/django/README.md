# Translator App Django Connector

Copy `translator_client` into your Django project or package it as an internal dependency.

```python
from translator_client import TranslatorClient

client = TranslatorClient(
    base_url="https://translation.example.com",
    api_key="trn_xxxxxxxx_secret",
)

result = client.translate(
    text="<p>Hello world</p>",
    source_language="en",
    target_language="bn",
    content_format="html",
    provider="openai",
    model="gpt-4.1-mini",
    external_content_id="article-123",
    content_type="article",
    title="Hello world",
)

print(result["translated_text"])
```

For Django settings:

```python
TRANSLATOR_APP_API_BASE_URL = "https://translation.example.com"
TRANSLATOR_APP_API_KEY = "trn_xxxxxxxx_secret"
```
