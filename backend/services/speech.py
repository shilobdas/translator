from dataclasses import dataclass
import os

import requests


class SpeechServiceError(Exception):
    pass


@dataclass
class SpeechTextResult:
    text: str
    provider: str


@dataclass
class SpeechAudioResult:
    audio_base64: str
    mime_type: str
    provider: str


def transcribe_audio(filename: str, content: bytes, content_type: str) -> SpeechTextResult:
    provider = os.getenv("SPEECH_TO_TEXT_PROVIDER", "demo").strip().lower()
    if provider in {"", "demo"}:
        raise SpeechServiceError(
            "Speech-to-text is not configured. Add a transcript or configure a provider."
        )
    if provider != "custom":
        raise SpeechServiceError(f"Unsupported SPEECH_TO_TEXT_PROVIDER: {provider}")

    endpoint = os.getenv("SPEECH_TO_TEXT_URL", "").strip()
    if not endpoint:
        raise SpeechServiceError("SPEECH_TO_TEXT_URL is required when SPEECH_TO_TEXT_PROVIDER=custom")

    files = {"audio_file": (filename, content, content_type or "application/octet-stream")}
    try:
        response = requests.post(
            endpoint,
            files=files,
            timeout=float(os.getenv("SPEECH_TIMEOUT_SECONDS", "30")),
        )
    except requests.RequestException as exc:
        raise SpeechServiceError(f"Speech-to-text request failed: {exc}") from exc

    if response.status_code >= 400:
        raise SpeechServiceError(
            f"Speech-to-text provider returned {response.status_code}: {response.text}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise SpeechServiceError("Speech-to-text provider returned invalid JSON") from exc

    text = data.get("text") or data.get("transcript")
    if not text:
        raise SpeechServiceError("Speech-to-text response did not include text")

    return SpeechTextResult(text=text, provider="custom")


def synthesize_speech(text: str, language: str) -> SpeechAudioResult | None:
    provider = os.getenv("TEXT_TO_SPEECH_PROVIDER", "demo").strip().lower()
    if provider in {"", "demo"}:
        return None
    if provider != "custom":
        raise SpeechServiceError(f"Unsupported TEXT_TO_SPEECH_PROVIDER: {provider}")

    endpoint = os.getenv("TEXT_TO_SPEECH_URL", "").strip()
    if not endpoint:
        raise SpeechServiceError("TEXT_TO_SPEECH_URL is required when TEXT_TO_SPEECH_PROVIDER=custom")

    try:
        response = requests.post(
            endpoint,
            json={"text": text, "language": language},
            timeout=float(os.getenv("SPEECH_TIMEOUT_SECONDS", "30")),
        )
    except requests.RequestException as exc:
        raise SpeechServiceError(f"Text-to-speech request failed: {exc}") from exc

    if response.status_code >= 400:
        raise SpeechServiceError(
            f"Text-to-speech provider returned {response.status_code}: {response.text}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise SpeechServiceError("Text-to-speech provider returned invalid JSON") from exc

    audio_base64 = data.get("audio_base64")
    if not audio_base64:
        raise SpeechServiceError("Text-to-speech response did not include audio_base64")

    return SpeechAudioResult(
        audio_base64=audio_base64,
        mime_type=data.get("mime_type", "audio/mpeg"),
        provider="custom",
    )
