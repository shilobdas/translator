import requests


class TranslatorClientError(Exception):
    pass


class TranslatorClient:
    def __init__(self, base_url, api_key, timeout=45):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    @property
    def headers(self):
        return {"X-API-Key": self.api_key}

    def translate(
        self,
        text,
        target_language,
        source_language="en",
        content_format="text",
        provider=None,
        model=None,
        **metadata,
    ):
        endpoint = "/api/v1/translate/html" if content_format == "html" else "/api/v1/translate"
        payload = {
            "text": text,
            "source_language": source_language,
            "target_language": target_language,
            "format": content_format,
            **metadata,
        }
        if provider:
            payload["provider"] = provider
        if model:
            payload["model"] = model
        return self._post(endpoint, payload)

    def translate_batch(
        self,
        items,
        target_language,
        source_language="en",
        callback_url=None,
        provider=None,
        model=None,
    ):
        payload = {
            "items": items,
            "source_language": source_language,
            "target_language": target_language,
            "callback_url": callback_url,
        }
        if provider:
            payload["provider"] = provider
        if model:
            payload["model"] = model
        return self._post(
            "/api/v1/translate/batch",
            payload,
        )

    def sync_content(self, external_content_id, text, target_language, source_language="en", content_format="text", **metadata):
        payload = {
            "external_content_id": external_content_id,
            "text": text,
            "target_language": target_language,
            "source_language": source_language,
            "format": content_format,
            **metadata,
        }
        return self._post("/api/v1/content/sync", payload)

    def list_content(self, **params):
        return self._get("/api/v1/content", params=params)

    def get_job(self, job_id):
        return self._get(f"/api/v1/jobs/{job_id}")

    def _get(self, endpoint, **kwargs):
        response = requests.get(
            self.base_url + endpoint,
            headers=self.headers,
            timeout=self.timeout,
            **kwargs,
        )
        return self._handle_response(response)

    def _post(self, endpoint, payload):
        response = requests.post(
            self.base_url + endpoint,
            json=payload,
            headers=self.headers,
            timeout=self.timeout,
        )
        return self._handle_response(response)

    @staticmethod
    def _handle_response(response):
        try:
            payload = response.json()
        except ValueError:
            payload = {"detail": response.text}

        if response.status_code >= 400:
            raise TranslatorClientError(payload.get("detail", "Translator App API request failed"))
        return payload
