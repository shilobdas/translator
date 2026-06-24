import base64
import csv
import io
import os

import requests
import streamlit as st

st.set_page_config(page_title="Translator App", page_icon="", layout="wide")

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
LANGUAGES = {
    "English": "en",
    "Spanish": "es",
    "French": "fr",
    "German": "de",
    "Japanese": "ja",
    "Arabic": "ar",
    "Bengali": "bn",
    "Chinese": "zh",
    "Hindi": "hi",
    "Italian": "it",
    "Portuguese": "pt",
}
TRANSLATION_PROVIDERS = {
    "Server default": "",
    "NLLB": "nllb",
    "OpenAI": "openai",
    "Gemini": "gemini",
    "LibreTranslate": "libretranslate",
    "Demo": "demo",
}


def init_session_state():
    defaults = {
        "logged_in": False,
        "username": None,
        "is_admin": False,
        "access_token": None,
        "refresh_token": None,
        "page": "internal_translate",
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def get_headers():
    return {"Authorization": f"Bearer {st.session_state.access_token}"}


def parse_error(response, fallback):
    try:
        detail = response.json().get("detail", fallback)
        return detail if isinstance(detail, str) else str(detail)
    except ValueError:
        return response.text or fallback


def request_json(method, path, **kwargs):
    try:
        response = requests.request(
            method,
            f"{API_BASE_URL}{path}",
            timeout=kwargs.pop("timeout", 20),
            **kwargs,
        )
    except requests.exceptions.ConnectionError:
        return None, "Connection error: FastAPI is not running."
    except requests.exceptions.Timeout:
        return None, "Timeout: backend is not responding."
    except requests.RequestException as exc:
        return None, str(exc)

    if 200 <= response.status_code < 300:
        if not response.content:
            return {}, None
        return response.json(), None

    return None, parse_error(response, f"Request failed with {response.status_code}.")


def fetch_auth_config():
    return request_json("GET", "/api/auth/config", timeout=10)


def register_user(username, password):
    return request_json(
        "POST",
        "/api/auth/register",
        data={"username": username, "password": password},
        timeout=10,
    )


def authenticate_user(username, password):
    return request_json(
        "POST",
        "/api/auth/login",
        data={"username": username, "password": password},
        timeout=10,
    )


def change_password(current_password, new_password):
    return request_json(
        "POST",
        "/api/auth/change-password",
        headers=get_headers(),
        data={"current_password": current_password, "new_password": new_password},
        timeout=10,
    )


def fetch_provider_status():
    return request_json("GET", "/api/providers", headers=get_headers(), timeout=10)


def fetch_internal_languages():
    return request_json("GET", "/api/internal/languages", headers=get_headers(), timeout=10)


def fetch_internal_provider_health():
    return request_json("GET", "/api/internal/provider/health", headers=get_headers(), timeout=10)


def fetch_profile():
    return request_json("GET", "/api/me", headers=get_headers(), timeout=10)


def fetch_my_history(filters):
    return request_json(
        "GET",
        "/api/me/history",
        headers=get_headers(),
        params=filters,
        timeout=15,
    )


def delete_my_translation(translation_id):
    return request_json(
        "DELETE",
        f"/api/me/history/{translation_id}",
        headers=get_headers(),
        timeout=10,
    )


def fetch_admin_stats():
    return request_json("GET", "/api/admin/stats", headers=get_headers(), timeout=10)


def fetch_admin_users():
    return request_json("GET", "/api/admin/users", headers=get_headers(), timeout=15)


def create_admin_user(username, password, is_active, is_admin):
    return request_json(
        "POST",
        "/api/internal/admin/users",
        headers=get_headers(),
        json={
            "username": username,
            "password": password,
            "is_active": is_active,
            "is_admin": is_admin,
        },
        timeout=10,
    )


def update_admin_user(user_id, is_active, is_admin):
    return request_json(
        "PATCH",
        f"/api/admin/users/{user_id}",
        headers=get_headers(),
        json={"is_active": is_active, "is_admin": is_admin},
        timeout=10,
    )


def admin_reset_password(user_id, new_password):
    return request_json(
        "POST",
        f"/api/admin/users/{user_id}/reset-password",
        headers=get_headers(),
        data={"new_password": new_password},
        timeout=10,
    )


def fetch_admin_history(filters):
    return request_json(
        "GET",
        "/api/admin/history",
        headers=get_headers(),
        params=filters,
        timeout=15,
    )


def fetch_admin_usage_summary(group_by):
    return request_json(
        "GET",
        "/api/admin/usage/summary",
        headers=get_headers(),
        params={"group_by": group_by},
        timeout=15,
    )


def fetch_admin_usage_logs(filters):
    return request_json(
        "GET",
        "/api/admin/usage/logs",
        headers=get_headers(),
        params=filters,
        timeout=15,
    )


def fetch_internal_usage_summary():
    return request_json(
        "GET",
        "/api/internal/admin/usage/summary",
        headers=get_headers(),
        timeout=15,
    )


def fetch_internal_activities(filters):
    return request_json(
        "GET",
        "/api/internal/admin/activities",
        headers=get_headers(),
        params=filters,
        timeout=15,
    )


def fetch_integrations():
    return request_json("GET", "/api/admin/integrations", headers=get_headers(), timeout=15)


def create_integration(name, platform, site_url, webhook_url):
    return request_json(
        "POST",
        "/api/admin/integrations",
        headers=get_headers(),
        json={
            "name": name,
            "platform": platform,
            "site_url": site_url,
            "webhook_url": webhook_url or None,
        },
        timeout=15,
    )


def update_integration(integration_id, name, site_url, webhook_url, is_active):
    return request_json(
        "PATCH",
        f"/api/admin/integrations/{integration_id}",
        headers=get_headers(),
        json={
            "name": name,
            "site_url": site_url,
            "webhook_url": webhook_url or None,
            "is_active": is_active,
        },
        timeout=15,
    )


def rotate_integration_key(integration_id):
    return request_json(
        "POST",
        f"/api/admin/integrations/{integration_id}/rotate-key",
        headers=get_headers(),
        timeout=15,
    )


def perform_text_translation(text, source_lang, target_lang, provider, model):
    payload = {
        "text": text,
        "source_language": source_lang,
        "target_language": target_lang,
    }
    if provider:
        payload["provider"] = provider
    if model:
        payload["model"] = model
    return request_json(
        "POST",
        "/api/translate/text",
        headers=get_headers(),
        json=payload,
        timeout=86400,
    )


def perform_internal_text_translation(text, source_lang, target_lang):
    return request_json(
        "POST",
        "/api/internal/translate/text",
        headers=get_headers(),
        json={
            "text": text,
            "source_language": source_lang,
            "target_language": target_lang,
        },
        timeout=86400,
    )


def perform_internal_document_translation(uploaded_file, source_lang, target_langs):
    files = {
        "file": (
            uploaded_file.name,
            uploaded_file.getvalue(),
            uploaded_file.type or "application/octet-stream",
        )
    }
    return request_json(
        "POST",
        "/api/internal/translate/document",
        headers=get_headers(),
        data={
            "source_language": source_lang,
            "target_languages": ",".join(target_langs),
        },
        files=files,
        timeout=86400,
    )


def extract_internal_excel_columns(uploaded_file):
    files = {
        "file": (
            uploaded_file.name,
            uploaded_file.getvalue(),
            uploaded_file.type or "application/octet-stream",
        )
    }
    return request_json(
        "POST",
        "/api/internal/excel/columns",
        headers=get_headers(),
        files=files,
        timeout=86400,
    )


def perform_internal_excel_translation(uploaded_file, source_lang, target_langs, columns):
    files = {
        "file": (
            uploaded_file.name,
            uploaded_file.getvalue(),
            uploaded_file.type or "application/octet-stream",
        )
    }
    return request_json(
        "POST",
        "/api/internal/translate/excel",
        headers=get_headers(),
        data={
            "source_language": source_lang,
            "target_languages": ",".join(target_langs),
            "columns": ",".join(columns),
        },
        files=files,
        timeout=86400,
    )


def perform_voice_translation(
    transcript,
    source_lang,
    target_lang,
    provider,
    model,
    audio_file,
    include_audio,
):
    form_data = {
        "transcript": transcript,
        "source_language": source_lang,
        "target_language": target_lang,
        "include_audio": str(include_audio).lower(),
    }
    if provider:
        form_data["provider"] = provider
    if model:
        form_data["model"] = model
    files = None
    if audio_file is not None:
        files = {
            "audio_file": (
                audio_file.name,
                audio_file.getvalue(),
                audio_file.type or "application/octet-stream",
            )
        }

    return request_json(
        "POST",
        "/api/translate/voice",
        headers=get_headers(),
        data=form_data,
        files=files,
        timeout=86400,
    )


def rows_to_csv(rows):
    if not rows:
        return ""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def language_select(label, default_code):
    labels = list(LANGUAGES.keys())
    codes = list(LANGUAGES.values())
    index = codes.index(default_code) if default_code in codes else 0
    label_value = st.selectbox(label, labels, index=index)
    return LANGUAGES[label_value]


def internal_language_options():
    data, error = fetch_internal_languages()
    if error:
        st.warning(error)
        return {
            "Bengali": "bn",
            "Arabic": "ar",
            "Hindi": "hi",
            "Spanish": "es",
            "French": "fr",
            "German": "de",
            "English": "en",
        }
    return {item["name"]: item["code"] for item in data.get("languages", [])}


def internal_language_select(label, default_code="en"):
    options = internal_language_options()
    labels = list(options.keys())
    codes = list(options.values())
    index = codes.index(default_code) if default_code in codes else 0
    label_value = st.selectbox(label, labels, index=index)
    return options[label_value]


def internal_language_multiselect(label, default_codes=None):
    default_codes = default_codes or ["bn"]
    options = internal_language_options()
    labels = list(options.keys())
    default_labels = [label for label, code in options.items() if code in default_codes]
    selected_labels = st.multiselect(label, labels, default=default_labels)
    return [options[label] for label in selected_labels]


def translation_provider_select():
    provider_col, model_col = st.columns(2)
    with provider_col:
        provider_label = st.selectbox("Translation provider", list(TRANSLATION_PROVIDERS.keys()))
    with model_col:
        model = st.text_input("Model override", placeholder="Use provider default")
    return TRANSLATION_PROVIDERS[provider_label], model.strip()


def render_download_file(file_payload):
    content = base64.b64decode(file_payload["content_base64"])
    st.download_button(
        f"Download {file_payload['filename']}",
        content,
        file_name=file_payload["filename"],
        mime=file_payload.get("mime_type", "application/octet-stream"),
        use_container_width=True,
    )


def logout():
    st.session_state.logged_in = False
    st.session_state.username = None
    st.session_state.is_admin = False
    st.session_state.access_token = None
    st.session_state.refresh_token = None
    st.session_state.page = "internal_translate"
    st.rerun()


def render_auth():
    st.title("Translator App")
    config, _ = fetch_auth_config()
    allow_registration = bool((config or {}).get("allow_public_registration", False))
    if allow_registration:
        login_tab, register_tab = st.tabs(["Login", "Register"])
    else:
        login_tab = st.container()
        register_tab = None

    with login_tab:
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login")
        if submitted:
            data, error = authenticate_user(username, password)
            if error:
                st.error(error)
                return
            st.session_state.logged_in = True
            st.session_state.username = data["user"]["username"]
            st.session_state.is_admin = data["user"]["is_admin"]
            st.session_state.access_token = data["access_token"]
            st.session_state.refresh_token = data["refresh_token"]
            st.session_state.page = "internal_usage" if st.session_state.is_admin else "internal_translate"
            st.rerun()

    if register_tab is None:
        st.info("Internal access only. Ask an admin to create your account.")
    else:
        with register_tab:
            with st.form("register_form"):
                username = st.text_input("New Username")
                password = st.text_input("New Password", type="password")
                confirm_password = st.text_input("Confirm Password", type="password")
                submitted = st.form_submit_button("Create Account")
            if submitted:
                if not username or not password:
                    st.error("Username and password are required.")
                    return
                if password != confirm_password:
                    st.error("Passwords do not match.")
                    return
                data, error = register_user(username, password)
                if error:
                    st.error(error)
                    return
                if data.get("is_admin"):
                    st.success("Account created with admin access.")
                else:
                    st.success("Account created. You can log in now.")


def render_sidebar():
    with st.sidebar:
        st.markdown("### Translator App")
        st.write(f"**{st.session_state.username}**")
        st.markdown("#### Internal")
        if st.button("Internal Translate", use_container_width=True):
            st.session_state.page = "internal_translate"
            st.rerun()
        if st.button("Documents", use_container_width=True):
            st.session_state.page = "internal_documents"
            st.rerun()
        if st.button("Excel", use_container_width=True):
            st.session_state.page = "internal_excel"
            st.rerun()
        st.markdown("#### Existing Tools")
        if st.button("Translate", use_container_width=True):
            st.session_state.page = "translate"
            st.rerun()
        if st.button("My History", use_container_width=True):
            st.session_state.page = "history"
            st.rerun()
        if st.button("Profile", use_container_width=True):
            st.session_state.page = "profile"
            st.rerun()
        if st.session_state.is_admin:
            st.markdown("---")
            if st.button("Admin Overview", use_container_width=True):
                st.session_state.page = "admin_overview"
                st.rerun()
            if st.button("Admin Users", use_container_width=True):
                st.session_state.page = "admin_users"
                st.rerun()
            if st.button("Admin History", use_container_width=True):
                st.session_state.page = "admin_history"
                st.rerun()
            if st.button("Admin Usage", use_container_width=True):
                st.session_state.page = "admin_usage"
                st.rerun()
            if st.button("Internal Usage", use_container_width=True):
                st.session_state.page = "internal_usage"
                st.rerun()
            if st.button("Integrations", use_container_width=True):
                st.session_state.page = "integrations"
                st.rerun()
        st.markdown("---")
        st.button("Logout", on_click=logout, use_container_width=True)

<<<<<<< HEAD
def render_translate_page():
    st.header("Translate")
    st.caption(f"Provider: {os.getenv('TRANSLATION_PROVIDER', 'default')}")  # which provider is running
    mode = st.radio(...)
=======

def render_provider_notice():
    providers, error = fetch_provider_status()
    if error:
        st.warning(error)
        return
    translation = providers["translation"]
    speech = providers["speech_to_text"]
    tts = providers["text_to_speech"]
    if translation["demo_mode"]:
        st.warning("Translation is running in demo mode.")
    with st.expander("Provider status", expanded=False):
        st.json(
            {
                "translation": translation,
                "translation_options": providers.get("translation_options", []),
                "speech_to_text": speech,
                "text_to_speech": tts,
            }
        )

>>>>>>> 61fdeafb474200c6f3df7aa60572dcfb3f203aa4

def render_internal_provider_health():
    health, error = fetch_internal_provider_health()
    if error:
        st.warning(error)
        return False
    if health.get("ok"):
        st.caption(f"Internal provider: {health.get('provider', 'unknown')}")
        return True
    st.error(health.get("message", "Internal translation provider is not healthy."))
    return False


def render_internal_translate_page():
    st.header("Internal Translate")
    provider_ready = render_internal_provider_health()

    lang_col1, lang_col2 = st.columns(2)
    with lang_col1:
        source_lang = internal_language_select("Source language", "en")
    with lang_col2:
        target_lang = internal_language_select("Target language", "bn")

    input_col, output_col = st.columns(2)
    with input_col:
        source_text = st.text_area("Source text", height=280, placeholder="Type or paste text")
        translate = st.button("Translate", type="primary", disabled=not provider_ready)
    with output_col:
        st.text_area(
            "Translation",
            value=st.session_state.get("internal_translation_output", ""),
            height=280,
            disabled=True,
        )

    if translate:
        data, error = perform_internal_text_translation(source_text, source_lang, target_lang)
        if error:
            st.error(error)
            return
        st.session_state.internal_translation_output = data.get("translated_text", "")
        st.caption(f"Provider: {data.get('provider', 'unknown')}")
        st.rerun()


def render_internal_documents_page():
    st.header("Document Translation")
    provider_ready = render_internal_provider_health()
    col1, col2 = st.columns(2)
    with col1:
        source_lang = internal_language_select("Document source language", "en")
    with col2:
        target_langs = internal_language_multiselect("Target languages", ["bn"])

    uploaded_file = st.file_uploader("Upload .docx or .txt", type=["docx", "txt"])
    if st.button("Translate Document", type="primary", disabled=not provider_ready):
        if uploaded_file is None:
            st.error("Upload a .docx or .txt file.")
            return
        if not target_langs:
            st.error("Choose at least one target language.")
            return
        data, error = perform_internal_document_translation(uploaded_file, source_lang, target_langs)
        if error:
            st.error(error)
            return
        st.success("Document translated.")
        for file_payload in data.get("files", []):
            render_download_file(file_payload)


def render_internal_excel_page():
    st.header("Excel Translation")
    provider_ready = render_internal_provider_health()
    col1, col2 = st.columns(2)
    with col1:
        source_lang = internal_language_select("Excel source language", "en")
    with col2:
        target_langs = internal_language_multiselect("Target languages", ["bn"])

    uploaded_file = st.file_uploader("Upload .xlsx", type=["xlsx"])
    columns = []
    if uploaded_file is not None:
        data, error = extract_internal_excel_columns(uploaded_file)
        if error:
            st.warning(error)
        else:
            columns = data.get("columns", [])

    selected_columns = st.multiselect("Columns to translate", columns)
    if st.button("Translate Excel", type="primary", disabled=not provider_ready):
        if uploaded_file is None:
            st.error("Upload an .xlsx file.")
            return
        if not selected_columns:
            st.error("Choose at least one column.")
            return
        if not target_langs:
            st.error("Choose at least one target language.")
            return
        data, error = perform_internal_excel_translation(
            uploaded_file,
            source_lang,
            target_langs,
            selected_columns,
        )
        if error:
            st.error(error)
            return
        st.success(f"Excel translated. Rows translated: {data.get('rows_translated', 0)}")
        render_download_file(data["file"])


def render_translate_page():
    st.header("Translate")
<<<<<<< HEAD
=======
    render_provider_notice()
>>>>>>> 61fdeafb474200c6f3df7aa60572dcfb3f203aa4
    mode = st.radio("Mode", ["Text", "Voice"], horizontal=True)

    if "translate_source_lang" not in st.session_state:
        st.session_state.translate_source_lang = "en"
    if "translate_target_lang" not in st.session_state:
        st.session_state.translate_target_lang = "es"

    col1, col_swap, col2 = st.columns([5, 1, 5])
    with col1:
        source_lang = language_select("Source language", st.session_state.translate_source_lang)
        st.session_state.translate_source_lang = source_lang
    with col_swap:
        st.write("")
        st.write("")
        if st.button("⇄", use_container_width=True):
            st.session_state.translate_source_lang, st.session_state.translate_target_lang = (
                st.session_state.translate_target_lang,
                st.session_state.translate_source_lang,
            )
            st.rerun()
    with col2:
        target_lang = language_select("Target language", st.session_state.translate_target_lang)
        st.session_state.translate_target_lang = target_lang

    provider, model = translation_provider_select()

    if mode == "Text":
<<<<<<< HEAD
        text = st.text_area("Text",height=180,placeholder="Enter text to translate here...")
=======
        text = st.text_area("Text", "Hello, how are you?", height=180)
>>>>>>> 61fdeafb474200c6f3df7aa60572dcfb3f203aa4
        if st.button("Translate Text", type="primary"):
            data, error = perform_text_translation(text, source_lang, target_lang, provider, model)
            render_translation_result(data, error)
    else:
        audio_file = st.file_uploader("Audio file", type=["wav", "mp3", "m4a", "ogg"])
<<<<<<< HEAD
        transcript = st.text_area("Transcript", height=140,placeholder="Enter transcript text here...")
=======
        transcript = st.text_area("Transcript", "Hello, how are you?", height=140)
>>>>>>> 61fdeafb474200c6f3df7aa60572dcfb3f203aa4
        include_audio = st.checkbox("Return translated audio when a TTS provider is configured")
        if st.button("Translate Voice", type="primary"):
            data, error = perform_voice_translation(
                transcript, source_lang, target_lang, provider, model, audio_file, include_audio,
            )
            render_translation_result(data, error)


def render_translation_result(data, error):
    if error:
        st.error(error)
        return
    if data.get("demo_mode"):
        st.warning("Demo translation returned. Configure a provider for real output.")
    provider_label = data.get("provider", "unknown")
    translation_model = data.get("translation_model")
    if translation_model:
        st.caption(f"Provider: {provider_label} | Model: {translation_model}")
    else:
        st.caption(f"Provider: {provider_label}")
    if data.get("usage_tokens") is not None:
        st.caption(f"Provider tokens: {data['usage_tokens']}")
    if data.get("source_text"):
        st.subheader("Source")
        st.write(data["source_text"])
    st.subheader("Translation")
    st.write(data.get("translated_text", ""))
    if data.get("audio_error"):
        st.warning(data["audio_error"])
    if data.get("audio_base64"):
        audio_bytes = base64.b64decode(data["audio_base64"])
        st.audio(audio_bytes, format=data.get("audio_mime_type", "audio/mpeg"))


def render_history_page():
    st.header("My History")
    with st.form("history_filters"):
        col1, col2, col3, col4 = st.columns(4)
        q = col1.text_input("Search")
        model_type = col2.selectbox("Model", ["", "text", "voice"])
        source = col3.text_input("Source code")
        target = col4.text_input("Target code")
        submitted = st.form_submit_button("Apply")

    filters = {
        "q": q,
        "model_type": model_type,
        "source_language": source,
        "target_language": target,
        "limit": 200,
    }
    rows, error = fetch_my_history(filters)
    if error:
        st.error(error)
        return
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
        st.download_button(
            "Download CSV",
            rows_to_csv(rows),
            file_name="translation_history.csv",
            mime="text/csv",
        )
        with st.form("delete_translation"):
            translation_id = st.number_input("Delete translation ID", min_value=1, step=1)
            delete_submitted = st.form_submit_button("Delete")
        if delete_submitted:
            _, delete_error = delete_my_translation(int(translation_id))
            if delete_error:
                st.error(delete_error)
            else:
                st.success("Translation deleted.")
                st.rerun()
    else:
        st.info("No translation history found.")


def render_profile_page():
    st.header("Profile")
    profile, error = fetch_profile()
    if error:
        st.error(error)
        return
    col1, col2, col3 = st.columns(3)
    col1.metric("Username", profile["username"])
    col2.metric("Admin", "Yes" if profile["is_admin"] else "No")
    col3.metric("Active", "Yes" if profile["is_active"] else "No")

    st.subheader("Change Password")
    with st.form("change_password_form"):
        current_password = st.text_input("Current password", type="password")
        new_password = st.text_input("New password", type="password")
        confirm_password = st.text_input("Confirm new password", type="password")
        submitted = st.form_submit_button("Update Password")
    if submitted:
        if new_password != confirm_password:
            st.error("New passwords do not match.")
            return
        _, change_error = change_password(current_password, new_password)
        if change_error:
            st.error(change_error)
        else:
            st.success("Password changed.")


def render_admin_overview():
    st.header("Admin Overview")
    stats, error = fetch_admin_stats()
    if error:
        st.error(error)
        return
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Users", stats.get("total_users", 0))
    col2.metric("Active Users", stats.get("active_users", 0))
    col3.metric("Translations", stats.get("total_translations", 0))
    col4.metric("Est. Tokens", stats.get("estimated_tokens", 0))
    st.subheader("Providers")
    st.json(stats.get("providers", {}))
    st.subheader("Recent Translations")
    history = stats.get("recent_history", [])
    if history:
        st.dataframe(history, use_container_width=True, hide_index=True)
    else:
        st.info("No translation history found.")


def render_admin_users():
    st.header("Admin Users")
    with st.expander("Create Internal User", expanded=True):
        with st.form("create_internal_user"):
            col1, col2 = st.columns(2)
            new_username = col1.text_input("Username")
            new_password = col2.text_input("Temporary password", type="password")
            create_active = st.checkbox("Active", value=True)
            create_admin = st.checkbox("Admin")
            create_submitted = st.form_submit_button("Create User")
        if create_submitted:
            data, create_error = create_admin_user(
                new_username,
                new_password,
                create_active,
                create_admin,
            )
            if create_error:
                st.error(create_error)
            else:
                st.success(f"Created {data['username']}.")
                st.rerun()

    users, error = fetch_admin_users()
    if error:
        st.error(error)
        return
    if not users:
        st.info("No users found.")
        return
    st.dataframe(users, use_container_width=True, hide_index=True)

    user_options = {f"{user['id']} - {user['username']}": user for user in users}
    selected_label = st.selectbox("User", list(user_options.keys()))
    selected_user = user_options[selected_label]

    with st.form("edit_user_form"):
        is_active = st.checkbox("Active", value=selected_user["is_active"])
        is_admin = st.checkbox("Admin", value=selected_user["is_admin"])
        submitted = st.form_submit_button("Save User")
    if submitted:
        updated, update_error = update_admin_user(selected_user["id"], is_active, is_admin)
        if update_error:
            st.error(update_error)
        else:
            st.success(f"Updated {updated['username']}.")
            st.rerun()

    with st.form("reset_user_password"):
        new_password = st.text_input("New password", type="password")
        reset_submitted = st.form_submit_button("Reset Password")
    if reset_submitted:
        _, reset_error = admin_reset_password(selected_user["id"], new_password)
        if reset_error:
            st.error(reset_error)
        else:
            st.success("Password reset.")


def render_admin_history():
    st.header("Admin History")
    with st.form("admin_history_filters"):
        col1, col2, col3, col4, col5 = st.columns(5)
        q = col1.text_input("Search")
        username = col2.text_input("Username")
        model_type = col3.selectbox("Model", ["", "text", "voice"])
        source = col4.text_input("Source code")
        target = col5.text_input("Target code")
        submitted = st.form_submit_button("Apply")

    rows, error = fetch_admin_history(
        {
            "q": q,
            "username": username,
            "model_type": model_type,
            "source_language": source,
            "target_language": target,
            "limit": 100,
        }
    )
    if error:
        st.error(error)
        return
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
        st.download_button(
            "Download CSV",
            rows_to_csv(rows),
            file_name="admin_translation_history.csv",
            mime="text/csv",
        )
    else:
        st.info("No translation history found.")


def render_admin_usage():
    st.header("Admin Usage")
    group_by = st.selectbox("Group usage by", ["integration", "user", "provider"])
    summary, error = fetch_admin_usage_summary(group_by)
    if error:
        st.error(error)
        return

    col1, col2, col3 = st.columns(3)
    col1.metric("Requests", summary.get("total_requests", 0))
    col2.metric("Characters", summary.get("total_characters", 0))
    col3.metric("Estimated Tokens", summary.get("estimated_tokens", 0))

    groups = summary.get("groups", [])
    st.subheader("Summary")
    if groups:
        st.dataframe(groups, use_container_width=True, hide_index=True)
    else:
        st.info("No usage yet.")

    st.subheader("Recent Usage Logs")
    with st.form("usage_log_filters"):
        col1, col2, col3 = st.columns(3)
        integration_id = col1.text_input("Integration ID")
        user_id = col2.text_input("User ID")
        limit = col3.number_input("Limit", min_value=1, max_value=500, value=100)
        submitted = st.form_submit_button("Load Logs")

    filters = {"limit": int(limit)}
    if integration_id.strip():
        filters["integration_id"] = integration_id.strip()
    if user_id.strip():
        filters["user_id"] = user_id.strip()

    logs, logs_error = fetch_admin_usage_logs(filters)
    if logs_error:
        st.error(logs_error)
        return
    if logs:
        st.dataframe(logs, use_container_width=True, hide_index=True)
        st.download_button(
            "Download Usage CSV",
            rows_to_csv(logs),
            file_name="usage_logs.csv",
            mime="text/csv",
        )
    else:
        st.info("No usage logs found.")


def render_internal_usage():
    st.header("Internal Usage")
    summary, error = fetch_internal_usage_summary()
    if error:
        st.error(error)
        return

    totals = summary.get("totals", {})
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Text", totals.get("text_translations", 0))
    col2.metric("Docs", totals.get("documents_uploaded", 0))
    col3.metric("Excel Files", totals.get("excel_files_uploaded", 0))
    col4.metric("Excel Rows", totals.get("excel_rows_translated", 0))
    col5.metric("Characters", totals.get("character_count", 0))

    st.subheader("By Internal User")
    users = summary.get("users", [])
    if users:
        st.dataframe(users, use_container_width=True, hide_index=True)
    else:
        st.info("No internal usage yet.")

    st.subheader("Activity And Download History")
    with st.form("internal_activity_filters"):
        col1, col2, col3 = st.columns(3)
        user_id = col1.text_input("User ID")
        activity_type = col2.selectbox("Activity", ["", "text", "document", "excel"])
        limit = col3.number_input("Limit", min_value=1, max_value=500, value=100)
        submitted = st.form_submit_button("Load Activity")

    filters = {"limit": int(limit)}
    if user_id.strip():
        filters["user_id"] = user_id.strip()
    if activity_type:
        filters["activity_type"] = activity_type

    activities, activities_error = fetch_internal_activities(filters)
    if activities_error:
        st.error(activities_error)
        return
    if activities:
        st.dataframe(activities, use_container_width=True, hide_index=True)
        st.download_button(
            "Download Activity CSV",
            rows_to_csv(activities),
            file_name="internal_activity.csv",
            mime="text/csv",
        )
    else:
        st.info("No activity found.")


def render_integrations():
    st.header("Integrations")
    st.write("Create API keys for WordPress, Drupal, Django, or another external platform.")

    with st.form("create_integration"):
        col1, col2 = st.columns(2)
        name = col1.text_input("Name", "Main WordPress Site")
        platform = col2.selectbox("Platform", ["wordpress", "drupal", "django", "custom"])
        site_url = st.text_input("Site URL", "https://example.com")
        webhook_url = st.text_input("Webhook URL")
        submitted = st.form_submit_button("Create Integration")

    if submitted:
        data, error = create_integration(name, platform, site_url, webhook_url)
        if error:
            st.error(error)
        else:
            st.success(data["message"])
            st.code(data["api_key"], language="text")

    integrations, error = fetch_integrations()
    if error:
        st.error(error)
        return
    if not integrations:
        st.info("No integrations yet.")
        return

    st.subheader("Existing Integrations")
    st.dataframe(integrations, use_container_width=True, hide_index=True)

    options = {f"{item['id']} - {item['name']}": item for item in integrations}
    selected_label = st.selectbox("Edit integration", list(options.keys()))
    selected = options[selected_label]

    with st.form("edit_integration"):
        edit_name = st.text_input("Edit name", selected["name"])
        edit_site_url = st.text_input("Edit site URL", selected["site_url"])
        edit_webhook_url = st.text_input("Edit webhook URL", selected.get("webhook_url") or "")
        edit_active = st.checkbox("Active", selected["is_active"])
        save = st.form_submit_button("Save Integration")
    if save:
        data, update_error = update_integration(
            selected["id"],
            edit_name,
            edit_site_url,
            edit_webhook_url,
            edit_active,
        )
        if update_error:
            st.error(update_error)
        else:
            st.success(f"Updated {data['name']}.")
            st.rerun()

    if st.button("Rotate API Key"):
        data, rotate_error = rotate_integration_key(selected["id"])
        if rotate_error:
            st.error(rotate_error)
        else:
            st.success(data["message"])
            st.code(data["api_key"], language="text")


def main():
    init_session_state()
    if not st.session_state.logged_in:
        render_auth()
        return

    render_sidebar()
    if st.session_state.page == "internal_translate":
        render_internal_translate_page()
    elif st.session_state.page == "internal_documents":
        render_internal_documents_page()
    elif st.session_state.page == "internal_excel":
        render_internal_excel_page()
    elif st.session_state.page == "translate":
        render_translate_page()
    elif st.session_state.page == "history":
        render_history_page()
    elif st.session_state.page == "profile":
        render_profile_page()
    elif st.session_state.page == "admin_overview" and st.session_state.is_admin:
        render_admin_overview()
    elif st.session_state.page == "admin_users" and st.session_state.is_admin:
        render_admin_users()
    elif st.session_state.page == "admin_history" and st.session_state.is_admin:
        render_admin_history()
    elif st.session_state.page == "admin_usage" and st.session_state.is_admin:
        render_admin_usage()
    elif st.session_state.page == "internal_usage" and st.session_state.is_admin:
        render_internal_usage()
    elif st.session_state.page == "integrations" and st.session_state.is_admin:
        render_integrations()
    else:
        render_internal_translate_page()


if __name__ == "__main__":
    main()
