from datetime import datetime, timedelta
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import warnings
import threading
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, Field
import requests
from sqlalchemy import func
from sqlalchemy.orm import Session

try:
    from .database import Base, engine, get_db
    from .models import (
        ExternalContent,
        Integration,
        InternalTranslationActivity,
        Translation,
        TranslationJob,
        UsageLog,
        User,
    )
    from .services.document_translation import translate_document_bytes
    from .services.excel_translation import extract_xlsx_columns, translate_xlsx_bytes
    from .services.html_translation import translate_html
    from .services.internal_config import (
        internal_provider_health,
        internal_translation_provider,
        internal_translate_text,
        supported_internal_languages,
        validate_internal_language,
    )
    from .services.speech import SpeechServiceError, synthesize_speech, transcribe_audio
    from .services.translation import (
        TranslationServiceError,
        available_translation_providers,
        translate_text as run_translation,
    )
except ImportError:
    from database import Base, engine, get_db
    from models import (
        ExternalContent,
        Integration,
        InternalTranslationActivity,
        Translation,
        TranslationJob,
        UsageLog,
        User,
    )
    from services.document_translation import translate_document_bytes
    from services.excel_translation import extract_xlsx_columns, translate_xlsx_bytes
    from services.html_translation import translate_html
    from services.internal_config import (
        internal_provider_health,
        internal_translation_provider,
        internal_translate_text,
        supported_internal_languages,
        validate_internal_language,
    )
    from services.speech import SpeechServiceError, synthesize_speech, transcribe_audio
    from services.translation import (
        TranslationServiceError,
        available_translation_providers,
        translate_text as run_translation,
    )

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    if os.getenv("APP_ENV", "development").lower() == "production":
        raise RuntimeError("SECRET_KEY must be set when APP_ENV=production")
    SECRET_KEY = secrets.token_urlsafe(32)
    warnings.warn(
        "SECRET_KEY is not set. Using a temporary development key; "
        "set SECRET_KEY in .env for stable logins.",
        RuntimeWarning,
        stacklevel=2,
    )

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7

Base.metadata.create_all(bind=engine)

# Pre-load model on startup

def _preload_nllb():
    try:
        from .services.translation import _get_nllb_model
        print(">>> Pre-loading NLLB model in background...")
        _get_nllb_model()
        print(">>> NLLB model ready. You can now translate.")
    except Exception as exc:
        print(f">>> NLLB pre-load warning: {exc}")

threading.Thread(target=_preload_nllb, daemon=True).start()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def env_flag(name: str, default: bool = False) -> bool:
    fallback = "true" if default else "false"
    return os.getenv(name, fallback).strip().lower() in {"1", "true", "yes", "on"}

app = FastAPI(
    title="Translation API",
    description="Authentication, admin, and translation APIs",
    version="1.0.0",
)

cors_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://127.0.0.1:8501,http://localhost:8501").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
RATE_LIMIT_MAX_REQUESTS = int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "120"))
rate_limit_hits: dict[str, list[float]] = {}


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        client_host = request.client.host if request.client else "unknown"
        key = f"{client_host}:{request.url.path}"
        now = time.monotonic()
        recent_hits = [
            hit
            for hit in rate_limit_hits.get(key, [])
            if now - hit < RATE_LIMIT_WINDOW_SECONDS
        ]
        if len(recent_hits) >= RATE_LIMIT_MAX_REQUESTS:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please try again shortly."},
            )
        recent_hits.append(now)
        rate_limit_hits[key] = recent_hits

    return await call_next(request)


class TranslationRequest(BaseModel):
    text: str = Field(..., min_length=1)
    source_language: str = Field("en", min_length=2, max_length=10)
    target_language: str = Field("es", min_length=2, max_length=10)
    provider: str | None = Field(None, max_length=500)
    model: str | None = Field(None, max_length=600)


class UserUpdateRequest(BaseModel):
    is_active: bool | None = None
    is_admin: bool | None = None


class AdminUserCreateRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=8, max_length=255)
    is_active: bool = True
    is_admin: bool = False


class InternalTextTranslationRequest(BaseModel):
    text: str = Field(..., min_length=1)
    source_language: str = Field("en", min_length=2, max_length=10)
    target_language: str = Field(..., min_length=2, max_length=10)


class IntegrationCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    platform: str = Field(..., min_length=1, max_length=50)
    site_url: str = Field(..., min_length=1, max_length=500)
    webhook_url: str | None = Field(None, max_length=500)


class IntegrationUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    site_url: str | None = Field(None, min_length=1, max_length=500)
    webhook_url: str | None = Field(None, max_length=500)
    is_active: bool | None = None


class IntegrationTranslateRequest(BaseModel):
    text: str = Field(..., min_length=1)
    source_language: str = Field("en", min_length=2, max_length=10)
    target_language: str = Field(..., min_length=2, max_length=10)
    format: str = Field("text", pattern="^(text|html)$")
    provider: str | None = Field(None, max_length=50)
    model: str | None = Field(None, max_length=100)
    external_content_id: str | None = Field(None, max_length=255)
    content_type: str | None = Field(None, max_length=100)
    title: str | None = Field(None, max_length=500)
    metadata: dict | None = None


class BatchTranslationItem(BaseModel):
    external_content_id: str = Field(..., min_length=1, max_length=255)
    content_type: str = Field("post", max_length=100)
    title: str | None = Field(None, max_length=500)
    text: str = Field(..., min_length=1)
    format: str = Field("text", pattern="^(text|html)$")
    provider: str | None = Field(None, max_length=50)
    model: str | None = Field(None, max_length=100)
    metadata: dict | None = None


class BatchTranslationRequest(BaseModel):
    source_language: str = Field("en", min_length=2, max_length=10)
    target_language: str = Field(..., min_length=2, max_length=10)
    provider: str | None = Field(None, max_length=50)
    model: str | None = Field(None, max_length=100)
    callback_url: str | None = Field(None, max_length=500)
    items: list[BatchTranslationItem] = Field(..., min_length=1, max_length=100)


class ContentSyncRequest(BaseModel):
    external_content_id: str = Field(..., min_length=1, max_length=255)
    content_type: str = Field("post", max_length=100)
    title: str | None = Field(None, max_length=500)
    source_language: str = Field("en", min_length=2, max_length=10)
    target_language: str = Field(..., min_length=2, max_length=10)
    format: str = Field("text", pattern="^(text|html)$")
    text: str = Field(..., min_length=1)
    metadata: dict | None = None


class PublishRequest(BaseModel):
    status: str = Field("ready", max_length=50)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_user_record(
    db: Session,
    username: str,
    password: str,
    is_active: bool = True,
    is_admin: bool = False,
) -> User:
    username = username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username is required")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=400, detail="Username already registered")

    user = User(
        username=username,
        hashed_password=get_password_hash(password),
        is_active=is_active,
        is_admin=is_admin,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_token(data: dict, expires_delta: timedelta, token_type: str = "access") -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + expires_delta
    to_encode.update({"exp": expire, "type": token_type})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        token_type = payload.get("type")
        if username is None or token_type != "access":
            raise credentials_exception
    except JWTError as exc:
        raise credentials_exception from exc

    user = db.query(User).filter(User.username == username).first()
    if user is None or not user.is_active:
        raise credentials_exception
    return user


def get_current_admin_user(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


def serialize_translation(translation: Translation, truncate: bool = False) -> dict:
    source = translation.source_text or ""
    target = translation.target_text or ""
    if truncate:
        source = source[:50] + "..." if len(source) > 50 else source
        target = target[:50] + "..." if len(target) > 50 else target
    return {
        "id": translation.id,
        "username": translation.user.username if translation.user else "unknown",
        "source": source,
        "target": target,
        "source_language": translation.source_language,
        "target_language": translation.target_language,
        "model": translation.model_type,
        "date": translation.created_at.isoformat(),
    }


def serialize_user(user: User, db: Session) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "is_active": user.is_active,
        "is_admin": user.is_admin,
        "created_at": user.created_at.isoformat(),
        "translation_count": db.query(Translation).filter(Translation.user_id == user.id).count(),
    }


def filtered_translation_query(
    db: Session,
    user_id: int | None = None,
    q: str | None = None,
    source_language: str | None = None,
    target_language: str | None = None,
    model_type: str | None = None,
):
    query = db.query(Translation)
    if user_id is not None:
        query = query.filter(Translation.user_id == user_id)
    if q:
        pattern = f"%{q.strip()}%"
        query = query.filter(
            Translation.source_text.ilike(pattern) | Translation.target_text.ilike(pattern)
        )
    if source_language:
        query = query.filter(Translation.source_language == source_language)
    if target_language:
        query = query.filter(Translation.target_language == target_language)
    if model_type:
        query = query.filter(Translation.model_type.ilike(f"{model_type}%"))
    return query.order_by(Translation.created_at.desc())


def provider_status() -> dict:
    translation_provider = os.getenv("TRANSLATION_PROVIDER", "demo").strip().lower() or "demo"
    speech_provider = os.getenv("SPEECH_TO_TEXT_PROVIDER", "demo").strip().lower() or "demo"
    tts_provider = os.getenv("TEXT_TO_SPEECH_PROVIDER", "demo").strip().lower() or "demo"
    translation_options = available_translation_providers()
    selected_translation = next(
        (
            option
            for option in translation_options
            if option["id"] == translation_provider
        ),
        None,
    )
    if selected_translation is None:
        selected_translation = {
            "id": translation_provider,
            "label": translation_provider,
            "selected": True,
            "configured": False,
            "demo_mode": False,
            "default_model": None,
        }
    return {
        "translation": {
            "provider": selected_translation["id"],
            "label": selected_translation["label"],
            "configured": selected_translation["configured"],
            "demo_mode": selected_translation["demo_mode"],
            "default_model": selected_translation["default_model"],
        },
        "translation_options": translation_options,
        "speech_to_text": {
            "provider": speech_provider,
            "configured": speech_provider == "demo"
            or bool(os.getenv("SPEECH_TO_TEXT_URL", "").strip()),
            "demo_mode": speech_provider == "demo",
        },
        "text_to_speech": {
            "provider": tts_provider,
            "configured": tts_provider == "demo"
            or bool(os.getenv("TEXT_TO_SPEECH_URL", "").strip()),
            "demo_mode": tts_provider == "demo",
        },
    }


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def clean_optional_text(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


def result_model_type(scope: str, result, max_length: int = 100) -> str:
    label = result.model or result.provider
    return f"{scope}:{label}"[:max_length]


def log_usage(
    db: Session,
    route: str,
    provider: str,
    model_type: str,
    source_language: str,
    target_language: str,
    source_text: str,
    target_text: str,
    user: User | None = None,
    integration: Integration | None = None,
    token_count: int | None = None,
) -> UsageLog:
    character_count = len(source_text or "") + len(target_text or "")
    total_tokens = token_count
    if total_tokens is None:
        total_tokens = estimate_tokens(source_text) + estimate_tokens(target_text)
    usage = UsageLog(
        user_id=user.id if user else None,
        integration_id=integration.id if integration else None,
        actor_type="integration" if integration else "user",
        route=route,
        provider=provider,
        model_type=model_type,
        source_language=source_language,
        target_language=target_language,
        character_count=character_count,
        estimated_tokens=total_tokens,
    )
    db.add(usage)
    db.commit()
    db.refresh(usage)
    return usage


def serialize_usage_log(usage: UsageLog) -> dict:
    return {
        "id": usage.id,
        "user_id": usage.user_id,
        "integration_id": usage.integration_id,
        "actor_type": usage.actor_type,
        "route": usage.route,
        "provider": usage.provider,
        "model_type": usage.model_type,
        "source_language": usage.source_language,
        "target_language": usage.target_language,
        "character_count": usage.character_count,
        "estimated_tokens": usage.estimated_tokens,
        "created_at": usage.created_at.isoformat(),
    }


def parse_target_languages(value: str) -> list[str]:
    raw_languages = [
        item.strip().lower()
        for item in (value or "").replace(";", ",").split(",")
        if item.strip()
    ]
    if not raw_languages:
        raise HTTPException(status_code=400, detail="At least one target language is required")
    unique_languages = []
    for language in raw_languages:
        if language not in unique_languages:
            try:
                unique_languages.append(validate_internal_language(language, "target language"))
            except TranslationServiceError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
    return unique_languages


def serialize_internal_activity(activity: InternalTranslationActivity) -> dict:
    try:
        target_languages = json.loads(activity.target_languages)
    except ValueError:
        target_languages = []
    return {
        "id": activity.id,
        "user_id": activity.user_id,
        "username": activity.user.username if activity.user else "unknown",
        "activity_type": activity.activity_type,
        "source_language": activity.source_language,
        "target_languages": target_languages,
        "provider": activity.provider,
        "model": activity.model,
        "character_count": activity.character_count,
        "text_translation_count": activity.text_translation_count,
        "document_count": activity.document_count,
        "excel_file_count": activity.excel_file_count,
        "excel_rows_translated": activity.excel_rows_translated,
        "source_filename": activity.source_filename,
        "output_filename": activity.output_filename,
        "download_mime_type": activity.download_mime_type,
        "created_at": activity.created_at.isoformat(),
    }


def log_internal_activity(
    db: Session,
    user: User,
    activity_type: str,
    source_language: str,
    target_languages: list[str],
    provider: str,
    model: str | None = None,
    character_count: int = 0,
    text_translation_count: int = 0,
    document_count: int = 0,
    excel_file_count: int = 0,
    excel_rows_translated: int = 0,
    source_filename: str | None = None,
    output_filename: str | None = None,
    download_mime_type: str | None = None,
) -> InternalTranslationActivity:
    activity = InternalTranslationActivity(
        user_id=user.id,
        activity_type=activity_type,
        source_language=source_language,
        target_languages=json.dumps(target_languages),
        provider=provider,
        model=model,
        character_count=character_count,
        text_translation_count=text_translation_count,
        document_count=document_count,
        excel_file_count=excel_file_count,
        excel_rows_translated=excel_rows_translated,
        source_filename=source_filename,
        output_filename=output_filename,
        download_mime_type=download_mime_type,
    )
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return activity


def encode_file_payload(filename: str, content: bytes, mime_type: str, target_language: str | None = None) -> dict:
    payload = {
        "filename": filename,
        "mime_type": mime_type,
        "content_base64": base64.b64encode(content).decode("ascii"),
    }
    if target_language:
        payload["target_language"] = target_language
    return payload


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def create_integration_api_key() -> tuple[str, str, str]:
    prefix = secrets.token_hex(4)
    secret = secrets.token_urlsafe(32)
    api_key = f"trn_{prefix}_{secret}"
    return api_key, prefix, hash_api_key(api_key)


def extract_api_key_prefix(api_key: str) -> str | None:
    parts = api_key.split("_", 2)
    if len(parts) != 3 or parts[0] != "trn":
        return None
    return parts[1]


def get_api_key_from_headers(
    x_api_key: str | None,
    authorization: str | None,
) -> str | None:
    if x_api_key:
        return x_api_key.strip()
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() in {"bearer", "apikey"} and value:
            return value.strip()
    return None


def get_current_integration(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> Integration:
    api_key = get_api_key_from_headers(x_api_key, authorization)
    if not api_key:
        raise HTTPException(status_code=401, detail="Integration API key is required")

    prefix = extract_api_key_prefix(api_key)
    if prefix is None:
        raise HTTPException(status_code=401, detail="Invalid integration API key")

    integration = (
        db.query(Integration)
        .filter(Integration.api_key_prefix == prefix, Integration.is_active.is_(True))
        .first()
    )
    if integration is None or not hmac.compare_digest(integration.api_key_hash, hash_api_key(api_key)):
        raise HTTPException(status_code=401, detail="Invalid integration API key")

    integration.last_used_at = datetime.utcnow()
    db.commit()
    db.refresh(integration)
    return integration


def serialize_integration(integration: Integration) -> dict:
    return {
        "id": integration.id,
        "name": integration.name,
        "platform": integration.platform,
        "site_url": integration.site_url,
        "webhook_url": integration.webhook_url,
        "api_key_prefix": integration.api_key_prefix,
        "is_active": integration.is_active,
        "created_at": integration.created_at.isoformat(),
        "last_used_at": integration.last_used_at.isoformat() if integration.last_used_at else None,
    }


def serialize_external_content(content: ExternalContent) -> dict:
    metadata = None
    if content.metadata_json:
        try:
            metadata = json.loads(content.metadata_json)
        except ValueError:
            metadata = None
    return {
        "id": content.id,
        "integration_id": content.integration_id,
        "platform": content.platform,
        "external_content_id": content.external_content_id,
        "content_type": content.content_type,
        "title": content.title,
        "source_language": content.source_language,
        "target_language": content.target_language,
        "format": content.content_format,
        "source_text": content.original_text,
        "translated_text": content.translated_text,
        "status": content.status,
        "metadata": metadata,
        "created_at": content.created_at.isoformat(),
        "updated_at": content.updated_at.isoformat(),
    }


def serialize_job(job: TranslationJob) -> dict:
    result = []
    if job.result_json:
        try:
            result = json.loads(job.result_json)
        except ValueError:
            result = []
    return {
        "id": job.id,
        "integration_id": job.integration_id,
        "status": job.status,
        "source_language": job.source_language,
        "target_language": job.target_language,
        "format": job.content_format,
        "item_count": job.item_count,
        "completed_count": job.completed_count,
        "error": job.error,
        "callback_url": job.callback_url,
        "result": result,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
    }


def translate_by_format(
    text: str,
    source_language: str,
    target_language: str,
    content_format: str,
    provider: str | None = None,
    model: str | None = None,
):
    if content_format == "html":
        return translate_html(text, source_language, target_language, provider, model)
    return run_translation(text, source_language, target_language, provider, model)


def upsert_external_content(
    db: Session,
    integration: Integration,
    external_content_id: str,
    content_type: str,
    title: str | None,
    source_language: str,
    target_language: str,
    content_format: str,
    source_text: str,
    translated_text: str | None,
    status_value: str,
    metadata: dict | None,
) -> ExternalContent:
    content = (
        db.query(ExternalContent)
        .filter(
            ExternalContent.integration_id == integration.id,
            ExternalContent.external_content_id == external_content_id,
            ExternalContent.target_language == target_language,
        )
        .first()
    )
    if content is None:
        content = ExternalContent(
            integration_id=integration.id,
            platform=integration.platform,
            external_content_id=external_content_id,
            content_type=content_type,
            target_language=target_language,
        )
        db.add(content)

    content.platform = integration.platform
    content.content_type = content_type
    content.title = title
    content.source_language = source_language
    content.target_language = target_language
    content.content_format = content_format
    content.original_text = source_text
    content.translated_text = translated_text
    content.status = status_value
    content.metadata_json = json.dumps(metadata or {})
    content.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(content)
    return content


def notify_webhook(url: str | None, payload: dict) -> str | None:
    if not url:
        return None
    try:
        response = requests.post(
            url,
            json=payload,
            timeout=float(os.getenv("WEBHOOK_TIMEOUT_SECONDS", "10")),
        )
        if response.status_code >= 400:
            return f"Webhook returned {response.status_code}: {response.text}"
    except requests.RequestException as exc:
        return f"Webhook request failed: {exc}"
    return None


@app.get("/api/health")
def health_check():
    return {"status": "ok"}


@app.get("/api/providers")
def get_provider_status(current_user: User = Depends(get_current_user)):
    return provider_status()


@app.get("/api/internal/languages")
def get_internal_languages(current_user: User = Depends(get_current_user)):
    return {"languages": supported_internal_languages()}


@app.get("/api/internal/provider/health")
def get_internal_provider_health(current_user: User = Depends(get_current_user)):
    return internal_provider_health()


@app.post("/api/internal/translate/text")
def internal_translate_text_endpoint(
    request: InternalTextTranslationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        source_language = validate_internal_language(request.source_language, "source language")
        target_language = validate_internal_language(request.target_language, "target language")
    except TranslationServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        result = internal_translate_text(request.text, source_language, target_language)
    except TranslationServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    new_translation = Translation(
        user_id=current_user.id,
        source_text=request.text,
        target_text=result.text,
        source_language=source_language,
        target_language=target_language,
        model_type=result_model_type("internal-text", result, max_length=50),
    )
    db.add(new_translation)
    db.commit()

    log_usage(
        db=db,
        route="/api/internal/translate/text",
        provider=result.provider,
        model_type=result_model_type("internal-text", result),
        source_language=source_language,
        target_language=target_language,
        source_text=request.text,
        target_text=result.text,
        user=current_user,
        token_count=result.usage_tokens,
    )
    activity = log_internal_activity(
        db=db,
        user=current_user,
        activity_type="text",
        source_language=source_language,
        target_languages=[target_language],
        provider=result.provider,
        model=result.model,
        character_count=len(request.text),
        text_translation_count=1,
    )

    return {
        "translated_text": result.text,
        "source_language": source_language,
        "target_language": target_language,
        "provider": result.provider,
        "translation_model": result.model,
        "usage_tokens": result.usage_tokens,
        "activity": serialize_internal_activity(activity),
    }


@app.post("/api/internal/translate/document")
async def internal_translate_document_endpoint(
    source_language: str = Form("en", min_length=2, max_length=10),
    target_languages: str = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        source_language = validate_internal_language(source_language, "source language")
        targets = parse_target_languages(target_languages)
        content = await file.read()
    except TranslationServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        translated_documents = translate_document_bytes(
            file.filename or "document",
            content,
            source_language,
            targets,
        )
    except TranslationServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    files = [
        encode_file_payload(
            document.filename,
            document.content,
            document.mime_type,
            document.target_language,
        )
        for document in translated_documents
    ]
    output_names = ", ".join(document.filename for document in translated_documents)
    activity = log_internal_activity(
        db=db,
        user=current_user,
        activity_type="document",
        source_language=source_language,
        target_languages=targets,
        provider=internal_translation_provider(),
        character_count=sum(document.character_count for document in translated_documents),
        document_count=1,
        source_filename=file.filename,
        output_filename=output_names,
        download_mime_type=translated_documents[0].mime_type if len(translated_documents) == 1 else "multiple",
    )

    return {
        "files": files,
        "activity": serialize_internal_activity(activity),
    }


@app.post("/api/internal/excel/columns")
async def internal_extract_excel_columns_endpoint(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    try:
        columns = extract_xlsx_columns(await file.read())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read Excel columns: {exc}") from exc
    return {"columns": columns}


@app.post("/api/internal/translate/excel")
async def internal_translate_excel_endpoint(
    source_language: str = Form("en", min_length=2, max_length=10),
    target_languages: str = Form(...),
    columns: str = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        source_language = validate_internal_language(source_language, "source language")
        targets = parse_target_languages(target_languages)
        selected_columns = [item.strip() for item in columns.split(",") if item.strip()]
    except TranslationServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        translated_excel = translate_xlsx_bytes(
            file.filename or "spreadsheet.xlsx",
            await file.read(),
            source_language,
            targets,
            selected_columns,
        )
    except TranslationServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    activity = log_internal_activity(
        db=db,
        user=current_user,
        activity_type="excel",
        source_language=source_language,
        target_languages=targets,
        provider=internal_translation_provider(),
        character_count=translated_excel.character_count,
        excel_file_count=1,
        excel_rows_translated=translated_excel.rows_translated,
        source_filename=file.filename,
        output_filename=translated_excel.filename,
        download_mime_type=translated_excel.mime_type,
    )

    return {
        "file": encode_file_payload(
            translated_excel.filename,
            translated_excel.content,
            translated_excel.mime_type,
        ),
        "rows_translated": translated_excel.rows_translated,
        "target_languages": translated_excel.target_languages,
        "activity": serialize_internal_activity(activity),
    }


@app.get("/api/me")
def get_my_profile(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "username": current_user.username,
        "is_active": current_user.is_active,
        "is_admin": current_user.is_admin,
        "created_at": current_user.created_at.isoformat(),
    }


@app.get("/api/me/history")
def get_my_history(
    q: str | None = None,
    source_language: str | None = None,
    target_language: str | None = None,
    model_type: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    translations = (
        filtered_translation_query(
            db,
            user_id=current_user.id,
            q=q,
            source_language=source_language,
            target_language=target_language,
            model_type=model_type,
        )
        .limit(limit)
        .all()
    )
    return [serialize_translation(item) for item in translations]


@app.delete("/api/me/history/{translation_id}")
def delete_my_translation(
    translation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    translation = (
        db.query(Translation)
        .filter(Translation.id == translation_id, Translation.user_id == current_user.id)
        .first()
    )
    if translation is None:
        raise HTTPException(status_code=404, detail="Translation not found")

    db.delete(translation)
    db.commit()
    return {"message": "Translation deleted"}


@app.post("/api/auth/register")
def register(
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    if not env_flag("ALLOW_PUBLIC_REGISTRATION", False):
        raise HTTPException(
            status_code=403,
            detail="Public registration is disabled. Ask an admin to create your account.",
        )
    username = username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username is required")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=400, detail="Username already registered")

    has_active_admin = (
        db.query(User)
        .filter(User.is_admin.is_(True), User.is_active.is_(True))
        .first()
        is not None
    )
    new_user = User(
        username=username,
        hashed_password=get_password_hash(password),
        is_active=True,
        is_admin=not has_active_admin,
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {
        "message": "User created successfully",
        "username": new_user.username,
        "is_admin": new_user.is_admin,
    }


@app.get("/api/auth/config")
def get_auth_config():
    return {
        "allow_public_registration": env_flag("ALLOW_PUBLIC_REGISTRATION", False),
        "internal_portal": True,
    }


@app.post("/api/auth/login")
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.username == form_data.username.strip()).first()

    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(status_code=403, detail="User account is inactive")

    access_token = create_token(
        data={"sub": user.username},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        token_type="access",
    )
    refresh_token = create_token(
        data={"sub": user.username},
        expires_delta=timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        token_type="refresh",
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "username": user.username,
            "is_admin": user.is_admin,
        },
    }


@app.post("/api/auth/refresh")
def refresh_access_token(
    refresh_token: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        payload = jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        token_type = payload.get("type")

        if username is None or token_type != "refresh":
            raise HTTPException(status_code=401, detail="Invalid refresh token")

        user = db.query(User).filter(User.username == username).first()
        if not user or not user.is_active:
            raise HTTPException(status_code=401, detail="User not found or inactive")

        new_access_token = create_token(
            data={"sub": user.username},
            expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
            token_type="access",
        )

        return {"access_token": new_access_token, "token_type": "bearer"}

    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Could not validate credentials") from exc


@app.post("/api/auth/change-password")
def change_password(
    current_password: str = Form(...),
    new_password: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")

    current_user.hashed_password = get_password_hash(new_password)
    db.commit()
    return {"message": "Password changed successfully"}


@app.get("/api/admin/stats")
def get_admin_stats(
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    total_users = db.query(User).count()
    total_translations = db.query(Translation).count()
    active_users = db.query(User).filter(User.is_active.is_(True)).count()
    recent_translations = (
        db.query(Translation)
        .order_by(Translation.created_at.desc())
        .limit(10)
        .all()
    )

    return {
        "total_users": total_users,
        "active_users": active_users,
        "total_translations": total_translations,
        "estimated_tokens": db.query(func.coalesce(func.sum(UsageLog.estimated_tokens), 0)).scalar(),
        "recent_history": [serialize_translation(item, truncate=True) for item in recent_translations],
        "providers": provider_status(),
    }


@app.get("/api/admin/usage/summary")
def get_admin_usage_summary(
    group_by: str = Query("integration", pattern="^(integration|user|provider)$"),
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    total_requests = db.query(UsageLog).count()
    total_characters = db.query(func.coalesce(func.sum(UsageLog.character_count), 0)).scalar()
    total_tokens = db.query(func.coalesce(func.sum(UsageLog.estimated_tokens), 0)).scalar()

    if group_by == "user":
        rows = (
            db.query(
                UsageLog.user_id,
                func.count(UsageLog.id),
                func.coalesce(func.sum(UsageLog.character_count), 0),
                func.coalesce(func.sum(UsageLog.estimated_tokens), 0),
            )
            .group_by(UsageLog.user_id)
            .all()
        )
        names = {user.id: user.username for user in db.query(User).all()}
        groups = [
            {
                "user_id": user_id,
                "name": names.get(user_id, "Unknown") if user_id else "No user",
                "request_count": request_count,
                "character_count": character_count,
                "estimated_tokens": estimated_tokens,
            }
            for user_id, request_count, character_count, estimated_tokens in rows
        ]
    elif group_by == "provider":
        rows = (
            db.query(
                UsageLog.provider,
                func.count(UsageLog.id),
                func.coalesce(func.sum(UsageLog.character_count), 0),
                func.coalesce(func.sum(UsageLog.estimated_tokens), 0),
            )
            .group_by(UsageLog.provider)
            .all()
        )
        groups = [
            {
                "provider": provider,
                "request_count": request_count,
                "character_count": character_count,
                "estimated_tokens": estimated_tokens,
            }
            for provider, request_count, character_count, estimated_tokens in rows
        ]
    else:
        rows = (
            db.query(
                UsageLog.integration_id,
                func.count(UsageLog.id),
                func.coalesce(func.sum(UsageLog.character_count), 0),
                func.coalesce(func.sum(UsageLog.estimated_tokens), 0),
            )
            .group_by(UsageLog.integration_id)
            .all()
        )
        names = {item.id: item.name for item in db.query(Integration).all()}
        groups = [
            {
                "integration_id": integration_id,
                "name": names.get(integration_id, "Unknown") if integration_id else "No integration",
                "request_count": request_count,
                "character_count": character_count,
                "estimated_tokens": estimated_tokens,
            }
            for integration_id, request_count, character_count, estimated_tokens in rows
        ]

    return {
        "group_by": group_by,
        "total_requests": total_requests,
        "total_characters": total_characters,
        "estimated_tokens": total_tokens,
        "groups": groups,
    }


@app.get("/api/admin/usage/logs")
def get_admin_usage_logs(
    integration_id: int | None = None,
    user_id: int | None = None,
    limit: int = Query(100, ge=1, le=500),
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    query = db.query(UsageLog)
    if integration_id is not None:
        query = query.filter(UsageLog.integration_id == integration_id)
    if user_id is not None:
        query = query.filter(UsageLog.user_id == user_id)
    logs = query.order_by(UsageLog.created_at.desc()).limit(limit).all()
    return [serialize_usage_log(item) for item in logs]


@app.get("/api/internal/admin/usage/summary")
def get_internal_admin_usage_summary(
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    totals = {
        "text_translations": db.query(
            func.coalesce(func.sum(InternalTranslationActivity.text_translation_count), 0)
        ).scalar(),
        "documents_uploaded": db.query(
            func.coalesce(func.sum(InternalTranslationActivity.document_count), 0)
        ).scalar(),
        "excel_files_uploaded": db.query(
            func.coalesce(func.sum(InternalTranslationActivity.excel_file_count), 0)
        ).scalar(),
        "excel_rows_translated": db.query(
            func.coalesce(func.sum(InternalTranslationActivity.excel_rows_translated), 0)
        ).scalar(),
        "character_count": db.query(
            func.coalesce(func.sum(InternalTranslationActivity.character_count), 0)
        ).scalar(),
        "activity_count": db.query(InternalTranslationActivity).count(),
    }

    rows = (
        db.query(
            InternalTranslationActivity.user_id,
            func.count(InternalTranslationActivity.id),
            func.coalesce(func.sum(InternalTranslationActivity.text_translation_count), 0),
            func.coalesce(func.sum(InternalTranslationActivity.document_count), 0),
            func.coalesce(func.sum(InternalTranslationActivity.excel_file_count), 0),
            func.coalesce(func.sum(InternalTranslationActivity.excel_rows_translated), 0),
            func.coalesce(func.sum(InternalTranslationActivity.character_count), 0),
            func.max(InternalTranslationActivity.created_at),
        )
        .group_by(InternalTranslationActivity.user_id)
        .all()
    )
    names = {user.id: user.username for user in db.query(User).all()}
    users = [
        {
            "user_id": user_id,
            "username": names.get(user_id, "Unknown"),
            "activity_count": activity_count,
            "text_translations": text_translations,
            "documents_uploaded": documents_uploaded,
            "excel_files_uploaded": excel_files_uploaded,
            "excel_rows_translated": excel_rows_translated,
            "character_count": character_count,
            "last_activity_at": last_activity_at.isoformat() if last_activity_at else None,
        }
        for (
            user_id,
            activity_count,
            text_translations,
            documents_uploaded,
            excel_files_uploaded,
            excel_rows_translated,
            character_count,
            last_activity_at,
        ) in rows
    ]

    return {
        "totals": totals,
        "users": users,
    }


@app.get("/api/internal/admin/activities")
def get_internal_admin_activities(
    user_id: int | None = None,
    activity_type: str | None = Query(None, pattern="^(text|document|excel)$"),
    limit: int = Query(100, ge=1, le=500),
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    query = db.query(InternalTranslationActivity)
    if user_id is not None:
        query = query.filter(InternalTranslationActivity.user_id == user_id)
    if activity_type:
        query = query.filter(InternalTranslationActivity.activity_type == activity_type)
    activities = query.order_by(InternalTranslationActivity.created_at.desc()).limit(limit).all()
    return [serialize_internal_activity(activity) for activity in activities]


@app.get("/api/admin/history")
def get_admin_history(
    q: str | None = None,
    username: str | None = None,
    source_language: str | None = None,
    target_language: str | None = None,
    model_type: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    query = filtered_translation_query(
        db,
        q=q,
        source_language=source_language,
        target_language=target_language,
        model_type=model_type,
    )
    if username:
        query = query.join(User).filter(User.username.ilike(f"%{username.strip()}%"))
    translations = query.limit(limit).all()
    return [serialize_translation(item) for item in translations]


@app.get("/api/admin/users")
def list_admin_users(
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    users = db.query(User).order_by(User.created_at.desc()).all()
    return [serialize_user(user, db) for user in users]


@app.post("/api/admin/users")
@app.post("/api/internal/admin/users")
def create_admin_user(
    request: AdminUserCreateRequest,
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    user = create_user_record(
        db=db,
        username=request.username,
        password=request.password,
        is_active=request.is_active,
        is_admin=request.is_admin,
    )
    return serialize_user(user, db)


@app.patch("/api/admin/users/{user_id}")
def update_admin_user(
    user_id: int,
    request: UserUpdateRequest,
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    would_disable_admin = (
        user.is_admin
        and user.is_active
        and (request.is_active is False or request.is_admin is False)
    )
    if would_disable_admin:
        active_admin_count = (
            db.query(User)
            .filter(User.is_admin.is_(True), User.is_active.is_(True))
            .count()
        )
        if active_admin_count <= 1:
            raise HTTPException(status_code=400, detail="At least one active admin is required")

    if user.id == current_admin.id and request.is_active is False:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account")

    if request.is_active is not None:
        user.is_active = request.is_active
    if request.is_admin is not None:
        user.is_admin = request.is_admin

    db.commit()
    db.refresh(user)
    return serialize_user(user, db)


@app.post("/api/admin/users/{user_id}/reset-password")
def admin_reset_password(
    user_id: int,
    new_password: str = Form(...),
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    user.hashed_password = get_password_hash(new_password)
    db.commit()
    return {"message": f"Password reset for {user.username}"}


@app.post("/api/admin/integrations")
def create_admin_integration(
    request: IntegrationCreateRequest,
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    api_key, prefix, api_key_hash = create_integration_api_key()
    integration = Integration(
        owner_user_id=current_admin.id,
        name=request.name.strip(),
        platform=request.platform.strip().lower(),
        site_url=request.site_url.strip(),
        webhook_url=request.webhook_url.strip() if request.webhook_url else None,
        api_key_prefix=prefix,
        api_key_hash=api_key_hash,
        is_active=True,
    )
    db.add(integration)
    db.commit()
    db.refresh(integration)

    return {
        **serialize_integration(integration),
        "api_key": api_key,
        "message": "Store this API key now. It will not be shown again.",
    }


@app.get("/api/admin/integrations")
def list_admin_integrations(
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    integrations = db.query(Integration).order_by(Integration.created_at.desc()).all()
    return [serialize_integration(integration) for integration in integrations]


@app.patch("/api/admin/integrations/{integration_id}")
def update_admin_integration(
    integration_id: int,
    request: IntegrationUpdateRequest,
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    integration = db.query(Integration).filter(Integration.id == integration_id).first()
    if integration is None:
        raise HTTPException(status_code=404, detail="Integration not found")

    if request.name is not None:
        integration.name = request.name.strip()
    if request.site_url is not None:
        integration.site_url = request.site_url.strip()
    if request.webhook_url is not None:
        integration.webhook_url = request.webhook_url.strip() or None
    if request.is_active is not None:
        integration.is_active = request.is_active

    db.commit()
    db.refresh(integration)
    return serialize_integration(integration)


@app.post("/api/admin/integrations/{integration_id}/rotate-key")
def rotate_admin_integration_key(
    integration_id: int,
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    integration = db.query(Integration).filter(Integration.id == integration_id).first()
    if integration is None:
        raise HTTPException(status_code=404, detail="Integration not found")

    api_key, prefix, api_key_hash = create_integration_api_key()
    integration.api_key_prefix = prefix
    integration.api_key_hash = api_key_hash
    db.commit()
    db.refresh(integration)
    return {
        **serialize_integration(integration),
        "api_key": api_key,
        "message": "Store this API key now. It will not be shown again.",
    }


@app.delete("/api/admin/integrations/{integration_id}")
def delete_admin_integration(
    integration_id: int,
    current_admin: User = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    integration = db.query(Integration).filter(Integration.id == integration_id).first()
    if integration is None:
        raise HTTPException(status_code=404, detail="Integration not found")

    db.delete(integration)
    db.commit()
    return {"message": "Integration deleted"}


@app.get("/api/v1/languages")
def list_integration_languages():
    return {
        "languages": [
            {"code": "en", "name": "English"},
            {"code": "es", "name": "Spanish"},
            {"code": "fr", "name": "French"},
            {"code": "de", "name": "German"},
            {"code": "ja", "name": "Japanese"},
            {"code": "ar", "name": "Arabic"},
            {"code": "bn", "name": "Bengali"},
            {"code": "zh", "name": "Chinese"},
            {"code": "hi", "name": "Hindi"},
            {"code": "it", "name": "Italian"},
            {"code": "pt", "name": "Portuguese"},
        ]
    }


@app.get("/api/v1/integration")
def get_integration_profile(
    integration: Integration = Depends(get_current_integration),
):
    return serialize_integration(integration)


@app.get("/api/v1/usage")
def get_integration_usage(
    limit: int = Query(100, ge=1, le=500),
    integration: Integration = Depends(get_current_integration),
    db: Session = Depends(get_db),
):
    total_requests = (
        db.query(UsageLog)
        .filter(UsageLog.integration_id == integration.id)
        .count()
    )
    total_characters = (
        db.query(func.coalesce(func.sum(UsageLog.character_count), 0))
        .filter(UsageLog.integration_id == integration.id)
        .scalar()
    )
    total_tokens = (
        db.query(func.coalesce(func.sum(UsageLog.estimated_tokens), 0))
        .filter(UsageLog.integration_id == integration.id)
        .scalar()
    )
    logs = (
        db.query(UsageLog)
        .filter(UsageLog.integration_id == integration.id)
        .order_by(UsageLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "integration": serialize_integration(integration),
        "total_requests": total_requests,
        "total_characters": total_characters,
        "estimated_tokens": total_tokens,
        "logs": [serialize_usage_log(item) for item in logs],
    }


@app.post("/api/v1/translate")
def integration_translate(
    request: IntegrationTranslateRequest,
    integration: Integration = Depends(get_current_integration),
    db: Session = Depends(get_db),
):
    try:
        result = translate_by_format(
            request.text,
            request.source_language,
            request.target_language,
            request.format,
            clean_optional_text(request.provider),
            clean_optional_text(request.model),
        )
    except TranslationServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    content = None
    if request.external_content_id:
        content = upsert_external_content(
            db=db,
            integration=integration,
            external_content_id=request.external_content_id,
            content_type=request.content_type or "content",
            title=request.title,
            source_language=request.source_language,
            target_language=request.target_language,
            content_format=request.format,
            source_text=request.text,
            translated_text=result.text,
            status_value="translated",
            metadata=request.metadata,
        )

    log_usage(
        db=db,
        route="/api/v1/translate/html" if request.format == "html" else "/api/v1/translate",
        provider=result.provider,
        model_type=result_model_type(f"integration:{request.format}", result),
        source_language=request.source_language,
        target_language=request.target_language,
        source_text=request.text,
        target_text=result.text,
        integration=integration,
        token_count=result.usage_tokens,
    )

    return {
        "translated_text": result.text,
        "provider": result.provider,
        "translation_model": result.model,
        "usage_tokens": result.usage_tokens,
        "demo_mode": result.demo_mode,
        "format": request.format,
        "content": serialize_external_content(content) if content else None,
    }


@app.post("/api/v1/translate/html")
def integration_translate_html(
    request: IntegrationTranslateRequest,
    integration: Integration = Depends(get_current_integration),
    db: Session = Depends(get_db),
):
    request.format = "html"
    return integration_translate(request, integration, db)


@app.post("/api/v1/translate/batch")
def integration_translate_batch(
    request: BatchTranslationRequest,
    integration: Integration = Depends(get_current_integration),
    db: Session = Depends(get_db),
):
    callback_url = request.callback_url or integration.webhook_url
    job = TranslationJob(
        integration_id=integration.id,
        status="running",
        source_language=request.source_language,
        target_language=request.target_language,
        content_format="mixed",
        item_count=len(request.items),
        completed_count=0,
        callback_url=callback_url,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    results = []
    try:
        for item in request.items:
            provider = clean_optional_text(item.provider) or clean_optional_text(request.provider)
            model = clean_optional_text(item.model) or clean_optional_text(request.model)
            result = translate_by_format(
                item.text,
                request.source_language,
                request.target_language,
                item.format,
                provider,
                model,
            )
            content = upsert_external_content(
                db=db,
                integration=integration,
                external_content_id=item.external_content_id,
                content_type=item.content_type,
                title=item.title,
                source_language=request.source_language,
                target_language=request.target_language,
                content_format=item.format,
                source_text=item.text,
                translated_text=result.text,
                status_value="translated",
                metadata=item.metadata,
            )
            results.append(
                {
                    "external_content_id": item.external_content_id,
                    "content_id": content.id,
                    "translated_text": result.text,
                    "provider": result.provider,
                    "translation_model": result.model,
                    "usage_tokens": result.usage_tokens,
                    "demo_mode": result.demo_mode,
                    "format": item.format,
                }
            )
            log_usage(
                db=db,
                route="/api/v1/translate/batch",
                provider=result.provider,
                model_type=result_model_type(f"integration-batch:{item.format}", result),
                source_language=request.source_language,
                target_language=request.target_language,
                source_text=item.text,
                target_text=result.text,
                integration=integration,
                token_count=result.usage_tokens,
            )
            job.completed_count += 1
            job.updated_at = datetime.utcnow()
            db.commit()

        job.status = "completed"
        job.result_json = json.dumps(results)
    except TranslationServiceError as exc:
        job.status = "failed"
        job.error = str(exc)
    except Exception as exc:
        job.status = "failed"
        job.error = str(exc)

    job.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(job)

    webhook_error = notify_webhook(callback_url, {"event": "translation.completed", "job": serialize_job(job)})
    if webhook_error and job.status == "completed":
        job.error = webhook_error
        db.commit()
        db.refresh(job)

    return serialize_job(job)


@app.get("/api/v1/jobs/{job_id}")
def get_integration_job(
    job_id: int,
    integration: Integration = Depends(get_current_integration),
    db: Session = Depends(get_db),
):
    job = (
        db.query(TranslationJob)
        .filter(TranslationJob.id == job_id, TranslationJob.integration_id == integration.id)
        .first()
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return serialize_job(job)


@app.post("/api/v1/content/sync")
def integration_sync_content(
    request: ContentSyncRequest,
    integration: Integration = Depends(get_current_integration),
    db: Session = Depends(get_db),
):
    content = upsert_external_content(
        db=db,
        integration=integration,
        external_content_id=request.external_content_id,
        content_type=request.content_type,
        title=request.title,
        source_language=request.source_language,
        target_language=request.target_language,
        content_format=request.format,
        source_text=request.text,
        translated_text=None,
        status_value="synced",
        metadata=request.metadata,
    )
    return serialize_external_content(content)


@app.get("/api/v1/content")
def list_integration_content(
    external_content_id: str | None = None,
    content_type: str | None = None,
    target_language: str | None = None,
    status_value: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    integration: Integration = Depends(get_current_integration),
    db: Session = Depends(get_db),
):
    query = db.query(ExternalContent).filter(ExternalContent.integration_id == integration.id)
    if external_content_id:
        query = query.filter(ExternalContent.external_content_id == external_content_id)
    if content_type:
        query = query.filter(ExternalContent.content_type == content_type)
    if target_language:
        query = query.filter(ExternalContent.target_language == target_language)
    if status_value:
        query = query.filter(ExternalContent.status == status_value)
    contents = query.order_by(ExternalContent.updated_at.desc()).limit(limit).all()
    return [serialize_external_content(content) for content in contents]


@app.get("/api/v1/content/{content_id}")
def get_integration_content(
    content_id: int,
    integration: Integration = Depends(get_current_integration),
    db: Session = Depends(get_db),
):
    content = (
        db.query(ExternalContent)
        .filter(ExternalContent.id == content_id, ExternalContent.integration_id == integration.id)
        .first()
    )
    if content is None:
        raise HTTPException(status_code=404, detail="Content not found")
    return serialize_external_content(content)


@app.post("/api/v1/content/{content_id}/publish")
def publish_integration_content(
    content_id: int,
    request: PublishRequest,
    integration: Integration = Depends(get_current_integration),
    db: Session = Depends(get_db),
):
    content = (
        db.query(ExternalContent)
        .filter(ExternalContent.id == content_id, ExternalContent.integration_id == integration.id)
        .first()
    )
    if content is None:
        raise HTTPException(status_code=404, detail="Content not found")
    if not content.translated_text:
        raise HTTPException(status_code=400, detail="Content has no translated text")

    content.status = request.status
    content.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(content)

    payload = {
        "event": "content.ready_to_publish",
        "content": serialize_external_content(content),
        "publish_payload": {
            "external_content_id": content.external_content_id,
            "content_type": content.content_type,
            "title": content.title,
            "target_language": content.target_language,
            "format": content.content_format,
            "translated_text": content.translated_text,
        },
    }
    webhook_error = notify_webhook(integration.webhook_url, payload)
    return {**payload, "webhook_error": webhook_error}


@app.post("/api/translate/text")
def translate_text(
    request: TranslationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = run_translation(
            request.text,
            request.source_language,
            request.target_language,
            clean_optional_text(request.provider),
            clean_optional_text(request.model),
        )
    except TranslationServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    new_translation = Translation(
        user_id=current_user.id,
        source_text=request.text,
        target_text=result.text,
        source_language=request.source_language,
        target_language=request.target_language,
        model_type=result_model_type("text", result, max_length=50),
    )
    db.add(new_translation)
    db.commit()
    log_usage(
        db=db,
        route="/api/translate/text",
        provider=result.provider,
        model_type=result_model_type("text", result),
        source_language=request.source_language,
        target_language=request.target_language,
        source_text=request.text,
        target_text=result.text,
        user=current_user,
        token_count=result.usage_tokens,
    )

    return {
        "translated_text": result.text,
        "model": "text",
        "provider": result.provider,
        "translation_model": result.model,
        "usage_tokens": result.usage_tokens,
        "demo_mode": result.demo_mode,
    }


@app.post("/api/translate/voice")
async def translate_voice(
    source_language: str = Form("en", min_length=2, max_length=10),
    target_language: str = Form("es", min_length=2, max_length=10),
    provider: str = Form(""),
    model: str = Form(""),
    transcript: str = Form(""),
    include_audio: bool = Form(False),
    audio_file: UploadFile | None = File(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    clean_transcript = transcript.strip()
    transcript_provider = "manual"
    if not clean_transcript:
        if audio_file is not None:
            audio_content = await audio_file.read()
            try:
                speech_result = transcribe_audio(
                    audio_file.filename or "audio",
                    audio_content,
                    audio_file.content_type or "application/octet-stream",
                )
            except SpeechServiceError as exc:
                status_code = 501 if "not configured" in str(exc).lower() else 502
                raise HTTPException(status_code=status_code, detail=str(exc)) from exc
            clean_transcript = speech_result.text.strip()
            transcript_provider = speech_result.provider
        else:
            raise HTTPException(status_code=400, detail="Transcript text or audio file is required")
    if not clean_transcript:
        raise HTTPException(status_code=400, detail="Transcript text is required")

    try:
        result = run_translation(
            clean_transcript,
            source_language,
            target_language,
            clean_optional_text(provider),
            clean_optional_text(model),
        )
    except TranslationServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    new_translation = Translation(
        user_id=current_user.id,
        source_text=clean_transcript,
        target_text=result.text,
        source_language=source_language,
        target_language=target_language,
        model_type=result_model_type("voice", result, max_length=50),
    )
    db.add(new_translation)
    db.commit()
    log_usage(
        db=db,
        route="/api/translate/voice",
        provider=result.provider,
        model_type=result_model_type("voice", result),
        source_language=source_language,
        target_language=target_language,
        source_text=clean_transcript,
        target_text=result.text,
        user=current_user,
        token_count=result.usage_tokens,
    )

    audio_result = None
    audio_error = None
    if include_audio:
        try:
            audio_result = synthesize_speech(result.text, target_language)
        except SpeechServiceError as exc:
            audio_error = str(exc)

    return {
        "translated_text": result.text,
        "model": "voice",
        "provider": result.provider,
        "translation_model": result.model,
        "usage_tokens": result.usage_tokens,
        "demo_mode": result.demo_mode,
        "source_text": clean_transcript,
        "transcript_provider": transcript_provider,
        "audio_filename": audio_file.filename if audio_file else None,
        "audio_base64": audio_result.audio_base64 if audio_result else None,
        "audio_mime_type": audio_result.mime_type if audio_result else None,
        "audio_provider": audio_result.provider if audio_result else None,
        "audio_error": audio_error,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
