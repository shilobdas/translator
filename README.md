# Translator App

Translator App is a FastAPI + Streamlit translation platform for user-facing translation, admin-managed integrations, and external CMS/framework clients such as WordPress, Drupal, Django, and custom applications.

It acts as a secure translation gateway: admins configure provider access on the Translator App server, then external clients receive only a Translator App integration API key. Clients never need direct OpenAI, Gemini, NLLB, or LibreTranslate credentials.

## Table Of Contents

- [What Translator App Does](#what-translator-app-does)
- [Architecture](#architecture)
- [Database Design](#database-design)
- [Security Model](#security-model)
- [Internal Translation Portal](#internal-translation-portal)
- [How To Run This Project](#how-to-run-this-project)
- [Local Setup](#local-setup)
- [Environment Configuration](#environment-configuration)
- [Provider Setup](#provider-setup)
- [Admin Workflow](#admin-workflow)
- [User Workflow](#user-workflow)
- [Integration API](#integration-api)
- [WordPress Integration](#wordpress-integration)
- [Drupal Integration](#drupal-integration)
- [Django Integration](#django-integration)
- [Custom Platform Integration](#custom-platform-integration)
- [Usage And Token Reporting](#usage-and-token-reporting)
- [Docker](#docker)
- [Production Checklist](#production-checklist)
- [Troubleshooting](#troubleshooting)
- [Current Limits And Upgrade Roadmap](#current-limits-and-upgrade-roadmap)

## What Translator App Does

- Provides user registration and JWT login.
- Supports internal-only login where admins create user accounts.
- Creates the first admin with a database command, not `.env` secrets.
- Supports text translation with selectable providers:
  - `nllb`
  - `openai`
  - `gemini`
  - `libretranslate`
  - `demo`
- Supports voice workflow hooks:
  - transcript translation
  - optional audio upload for speech-to-text
  - optional translated audio output for text-to-speech
- Stores user translation history.
- Gives admins user management, password reset, history search, and usage reporting.
- Creates integration API keys for external platforms.
- Provides HTML-safe translation that preserves tags, links, shortcodes, scripts, styles, and non-translatable blocks.
- Supports batch translation jobs for many posts/pages/items.
- Supports webhook callbacks for completed jobs and publish-ready content.
- Tracks usage by user, provider, integration, route, characters, and tokens.
- Tracks internal usage for text, document uploads, Excel uploads, translated rows, downloads, and timestamps.

## Architecture

```mermaid
flowchart LR
    Admin["Admin UI<br>Streamlit"] --> API["Translator App API<br>FastAPI"]
    User["User UI<br>Streamlit"] --> API
    WP["WordPress Plugin"] --> API
    DR["Drupal Module"] --> API
    DJ["Django Client"] --> API
    Custom["Custom Platform"] --> API

    API --> DB["Database<br>PostgreSQL"]
    API --> NLLB["NLLB Service"]
    API --> OpenAI["OpenAI Responses API"]
    API --> Gemini["Gemini generateContent API"]
    API --> Libre["LibreTranslate"]
    API --> Speech["Optional STT/TTS Services"]
```

Main project folders:

```text
backend/
  main.py                    FastAPI app and API routes
  models.py                  SQLAlchemy models
  database.py                DB configuration
  services/
    translation.py           NLLB, OpenAI, Gemini, LibreTranslate, demo providers
    internal_config.py       Internal provider/language config
    document_translation.py  DOCX/TXT translation
    excel_translation.py     XLSX column translation
    html_translation.py      HTML-safe translation
    speech.py                Speech-to-text and text-to-speech hooks

frontend/
  app.py                     Streamlit user/admin portal

connectors/
  wordpress/translator-app WordPress plugin
  drupal/translator_app    Drupal module with optional TMGMT provider
  django/translator_client        Django/Python client starter
```

## Database Design

Translator App uses PostgreSQL as the application database. All durable application data should live in PostgreSQL:

- users and admins
- password hashes
- integration records
- integration API key hashes
- user translation history
- external CMS content mappings
- batch translation jobs
- usage/token logs
- internal document/Excel/text activity logs

Do not store admin credentials in `.env`. Create or reset admins with:

```powershell
python -m backend.manage create-admin --username admin
```

### Database ER Diagram

```mermaid
erDiagram
    USERS ||--o{ TRANSLATIONS : creates
    USERS ||--o{ INTEGRATIONS : owns
    USERS ||--o{ INTERNAL_TRANSLATION_ACTIVITIES : performs
    USERS ||--o{ USAGE_LOGS : may_create
    INTEGRATIONS ||--o{ EXTERNAL_CONTENTS : tracks
    INTEGRATIONS ||--o{ TRANSLATION_JOBS : runs
    INTEGRATIONS ||--o{ USAGE_LOGS : may_create
    EXTERNAL_CONTENTS ||--o{ TRANSLATION_JOBS : may_reference

    USERS {
        int id PK
        string username UK
        string hashed_password
        boolean is_active
        boolean is_admin
        datetime created_at
    }

    TRANSLATIONS {
        int id PK
        int user_id FK
        text source_text
        text target_text
        string source_language
        string target_language
        string model_type
        datetime created_at
    }

    INTEGRATIONS {
        int id PK
        int owner_user_id FK
        string name
        string platform
        string site_url
        string webhook_url
        string api_key_prefix UK
        string api_key_hash
        boolean is_active
        datetime created_at
        datetime last_used_at
    }

    EXTERNAL_CONTENTS {
        int id PK
        int integration_id FK
        string platform
        string external_content_id
        string content_type
        string title
        string source_language
        string target_language
        string content_format
        text original_text
        text translated_text
        string status
        text metadata_json
        datetime created_at
        datetime updated_at
    }

    TRANSLATION_JOBS {
        int id PK
        int integration_id FK
        int external_content_id FK
        string status
        string source_language
        string target_language
        string content_format
        int item_count
        int completed_count
        text error
        string callback_url
        text result_json
        datetime created_at
        datetime updated_at
    }

    USAGE_LOGS {
        int id PK
        int user_id FK
        int integration_id FK
        string actor_type
        string route
        string provider
        string model_type
        string source_language
        string target_language
        int character_count
        int estimated_tokens
        datetime created_at
    }

    INTERNAL_TRANSLATION_ACTIVITIES {
        int id PK
        int user_id FK
        string activity_type
        string source_language
        text target_languages
        string provider
        string model
        int character_count
        int text_translation_count
        int document_count
        int excel_file_count
        int excel_rows_translated
        string source_filename
        string output_filename
        string download_mime_type
        datetime created_at
    }
```

### Table Summary

| Table | Purpose |
| --- | --- |
| `users` | Stores login accounts. Admins are normal users with `is_admin=true`. Passwords are stored as hashes. |
| `translations` | Stores per-user text/voice translation history shown in user history screens. |
| `integrations` | Stores external platform connections such as WordPress, Drupal, Django, and custom apps. |
| `external_contents` | Maps external CMS content IDs to translated text and status per target language. |
| `translation_jobs` | Stores batch translation job state, callbacks, results, and errors. |
| `usage_logs` | Stores usage accounting for internal users and external integrations. |
| `internal_translation_activities` | Stores internal portal activity for text, document, and Excel translation dashboards. |

### `users`

Stores internal users and admins.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | integer | Primary key. |
| `username` | string(255) | Unique, indexed, required. |
| `hashed_password` | string(255) | Required password hash. Plain passwords are never stored. |
| `is_active` | boolean | Controls login access. |
| `is_admin` | boolean | Grants admin features. |
| `created_at` | datetime | Creation timestamp. |

Relationships:

- One user can have many `translations`.
- One user can own many `integrations`.
- One user can have many `internal_translation_activities`.
- One user can appear in many `usage_logs`.

### `translations`

Stores user-facing translation history.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | integer | Primary key. |
| `user_id` | integer | Foreign key to `users.id`, cascades on delete. |
| `source_text` | text | Original text. |
| `target_text` | text | Translated text. |
| `source_language` | string(10) | Source language code. |
| `target_language` | string(10) | Target language code. |
| `model_type` | string(50) | Route/model label, such as text or voice. |
| `created_at` | datetime | Translation timestamp. |

### `integrations`

Stores external client applications and CMS connections.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | integer | Primary key. |
| `owner_user_id` | integer | Optional foreign key to `users.id`; database behavior is `SET NULL`. |
| `name` | string(255) | Human-readable integration name. |
| `platform` | string(50) | Example: `wordpress`, `drupal`, `django`, `custom`. |
| `site_url` | string(500) | Client site/application URL. |
| `webhook_url` | string(500) | Optional callback URL. |
| `api_key_prefix` | string(32) | Unique and indexed. Used to identify the key quickly. |
| `api_key_hash` | string(128) | Hash of the secret API key. The full key is shown once and not stored. |
| `is_active` | boolean | Enables/disables client access. |
| `created_at` | datetime | Creation timestamp. |
| `last_used_at` | datetime | Last successful API usage timestamp. |

Relationships:

- One integration can have many `external_contents`.
- One integration can have many `translation_jobs`.
- One integration can have many `usage_logs`.

### `external_contents`

Stores translated content mappings for WordPress, Drupal, Django, and custom clients.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | integer | Primary key. |
| `integration_id` | integer | Foreign key to `integrations.id`, cascades on delete. |
| `platform` | string(50) | Client platform. |
| `external_content_id` | string(255) | ID from the external platform, such as `wp-post-123-content`. |
| `content_type` | string(100) | External type, such as post, page, node, article. |
| `title` | string(500) | Optional title. |
| `source_language` | string(10) | Source language code. |
| `target_language` | string(10) | Target language code. |
| `content_format` | string(20) | `text`, `html`, or another supported format. |
| `original_text` | text | Source content. |
| `translated_text` | text | Translated output. |
| `status` | string(50) | Example: `synced`, `translated`, `published`. |
| `metadata_json` | text | JSON string for platform-specific metadata. |
| `created_at` | datetime | Creation timestamp. |
| `updated_at` | datetime | Update timestamp. |

Unique constraint:

```text
integration_id + external_content_id + target_language
```

This prevents duplicate translated rows for the same external item and target language.

### `translation_jobs`

Stores batch translation jobs for many external items.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | integer | Primary key. |
| `integration_id` | integer | Foreign key to `integrations.id`, cascades on delete. |
| `external_content_id` | integer | Optional foreign key to `external_contents.id`, database behavior is `SET NULL`. |
| `status` | string(50) | Example: `pending`, `running`, `completed`, `failed`. |
| `source_language` | string(10) | Source language code. |
| `target_language` | string(10) | Target language code. |
| `content_format` | string(20) | Job content format. |
| `item_count` | integer | Total items in the job. |
| `completed_count` | integer | Completed items. |
| `error` | text | Error details if the job fails. |
| `callback_url` | string(500) | Webhook callback URL. |
| `result_json` | text | JSON string containing job results. |
| `created_at` | datetime | Creation timestamp. |
| `updated_at` | datetime | Update timestamp. |

### `usage_logs`

Stores accounting data for admin dashboards and token/character reports.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | integer | Primary key. |
| `user_id` | integer | Optional foreign key to `users.id`, database behavior is `SET NULL`. |
| `integration_id` | integer | Optional foreign key to `integrations.id`, database behavior is `SET NULL`. |
| `actor_type` | string(50) | Example: `user`, `admin`, `integration`. |
| `route` | string(255) | API route used. |
| `provider` | string(100) | Provider used, such as `nllb`, `openai`, `gemini`. |
| `model_type` | string(100) | Model or feature label. |
| `source_language` | string(10) | Source language code. |
| `target_language` | string(10) | Target language code. |
| `character_count` | integer | Source/target character usage. |
| `estimated_tokens` | integer | Estimated or provider-reported token usage. |
| `created_at` | datetime | Usage timestamp. |

### `internal_translation_activities`

Stores internal portal activity history for admin usage dashboards.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | integer | Primary key. |
| `user_id` | integer | Foreign key to `users.id`, cascades on delete. |
| `activity_type` | string(50) | Example: `text`, `document`, `excel`. |
| `source_language` | string(10) | Source language code. |
| `target_languages` | text | JSON string/list of target language codes. |
| `provider` | string(100) | Provider used. |
| `model` | string(100) | Optional model name. |
| `character_count` | integer | Character usage. |
| `text_translation_count` | integer | Number of text translations. |
| `document_count` | integer | Number of translated documents. |
| `excel_file_count` | integer | Number of translated Excel files. |
| `excel_rows_translated` | integer | Count of translated Excel rows. |
| `source_filename` | string(500) | Uploaded source filename. |
| `output_filename` | string(500) | Generated output filename. |
| `download_mime_type` | string(255) | Output MIME type. |
| `created_at` | datetime | Activity timestamp. |

### Data Retention And Delete Behavior

- Deleting a user cascades to their `translations` and `internal_translation_activities`.
- Integration ownership can be nullable, but integrations should usually be managed through the admin UI instead of deleting owner users directly.
- Deleting an integration cascades to its `external_contents` and `translation_jobs`.
- `usage_logs` keep optional nullable links to users/integrations so historical usage can remain reportable.
- Provider secrets are not stored in these tables. Provider settings currently come from environment variables or a production secret manager.

### Migration Note

The current MVP creates tables from SQLAlchemy metadata at application startup. For production schema changes, add Alembic migrations before running this with live customer data.

## Security Model

Translator App uses two different kinds of keys:

```text
Provider keys:
  OPENAI_API_KEY
  GEMINI_API_KEY
  NLLB_TRANSLATION_URL / private NLLB endpoint
  LIBRETRANSLATE_API_KEY

Client keys:
  trn_xxxxxxxx_secret
```

Provider keys stay on the Translator App server. Do not put OpenAI, Gemini, or private model provider keys into WordPress, Drupal, Django, browser JavaScript, or mobile apps.

External platforms receive only a Translator App integration API key, for example:

```text
trn_xxxxxxxx_secret
```

That key allows the client to call Translator App. Translator App then decides which provider/model to use.

Current implementation note: provider connection settings are configured through environment variables, but users, admins, integrations, usage, history, documents, Excel activity, and API key hashes are stored in PostgreSQL. Do not store admin passwords in `.env`; create admins with the database command below.

## Internal Translation Portal

The internal portal is built inside the existing Translator App backend and frontend. It is intended for staff/internal users, not public self-service registration.

Internal features:

- Admin-created internal users.
- Public registration disabled by default.
- First admin creation through a PostgreSQL-backed command.
- Local/free NLLB provider by default.
- Google Translate-style text translation page.
- `.docx` upload and translated `.docx` download.
- `.txt` upload and translated `.txt` download.
- `.xlsx` upload with user-selected columns.
- Excel output keeps original columns and appends translated columns such as `description_bn`.
- Internal usage dashboard by user.
- Provider/model health endpoint.
- Supported languages endpoint.

Internal API endpoints:

```http
GET  /api/auth/config
GET  /api/internal/languages
GET  /api/internal/provider/health
POST /api/internal/admin/users
POST /api/internal/translate/text
POST /api/internal/translate/document
POST /api/internal/excel/columns
POST /api/internal/translate/excel
GET  /api/internal/admin/usage/summary
GET  /api/internal/admin/activities
```

Internal portal pages in Streamlit:

```text
Internal Translate
Documents
Excel
Internal Usage
Admin Users
```

The internal portal does not silently fake translations. If `INTERNAL_TRANSLATION_PROVIDER=nllb` and `NLLB_TRANSLATION_URL` is missing, users see a clear provider error.

## How To Run This Project

You can run Translator App in two ways:

- Docker Compose: easiest because it starts PostgreSQL, backend, and frontend.
- Manual local run: useful for development when you want backend/frontend terminals open separately.

### Option 1: Run With Docker Compose

From the project root:

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Docker starts:

```text
PostgreSQL: localhost:5432
Backend API: http://127.0.0.1:8000
Frontend UI: http://127.0.0.1:8501
```

Create the first admin account in another terminal:

```powershell
docker compose exec backend python -m backend.manage create-admin --username admin
```

Open the app:

```text
http://127.0.0.1:8501
```

Login with the admin username/password you created. Then open `Admin Users` to create internal users.

Check backend health:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

Stop Docker services:

```powershell
docker compose down
```

Stop and remove the PostgreSQL data volume:

```powershell
docker compose down -v
```

### Option 2: Run Manually On Your Machine

Install Python dependencies:

```powershell
python -m pip install -r requirements.txt
```

Create the environment file:

```powershell
Copy-Item .env.example .env
```

Start PostgreSQL with Docker:

```powershell
docker compose up -d postgres
```

Or use your own PostgreSQL server and update this value in `.env`:

```env
DATABASE_URL=postgresql://translator_app:translator_app_password@127.0.0.1:5432/translator_app
```

Create the first admin account:

```powershell
python -m backend.manage create-admin --username admin
```

Start the backend:

```powershell
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Start the frontend in a second terminal:

```powershell
python -m streamlit run frontend/app.py --server.address 127.0.0.1 --server.port 8501
```

Open:

```text
http://127.0.0.1:8501
```

Backend API docs are available at:

```text
http://127.0.0.1:8000/docs
```

### First Translation Provider Setup

By default, the internal portal expects local/free NLLB:

```env
INTERNAL_TRANSLATION_PROVIDER=nllb
NLLB_TRANSLATION_URL=http://127.0.0.1:9000/translate
```

If NLLB is not running, text/document/Excel translation will show a clear provider error. This is expected and prevents fake translations.

For a quick development-only UI test without NLLB, explicitly enable demo mode:

```env
INTERNAL_TRANSLATION_PROVIDER=demo
ALLOW_INTERNAL_DEMO_TRANSLATION=true
TRANSLATION_PROVIDER=demo
```

Restart the backend after changing `.env`.

### Run Checks

Compile Python files:

```powershell
python -m compileall backend frontend tests connectors\django
```

Run smoke tests:

```powershell
python tests\smoke_internal.py
```

## Local Setup

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Create environment file:

```powershell
Copy-Item .env.example .env
```

Start PostgreSQL first. With Docker:

```powershell
docker compose up -d postgres
```

Or use your own PostgreSQL server and set `DATABASE_URL` in `.env`.

Create the database tables and first admin with this command. It prompts for the password, hashes it, and stores it in PostgreSQL:

```powershell
python -m backend.manage create-admin --username admin
```

Start the backend:

```powershell
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Start the frontend in another terminal:

```powershell
python -m streamlit run frontend/app.py --server.address 127.0.0.1 --server.port 8501
```

Open:

```text
http://127.0.0.1:8501
```

Health check:

```text
http://127.0.0.1:8000/api/health
```

Login with the admin account, then create internal users from `Admin Users`.

## Environment Configuration

Copy `.env.example` to `.env` and update values:

```env
APP_ENV=development
DATABASE_URL=postgresql://translator_app:translator_app_password@127.0.0.1:5432/translator_app
SECRET_KEY=replace-this-with-a-long-random-secret
API_BASE_URL=http://127.0.0.1:8000
CORS_ORIGINS=http://127.0.0.1:8501,http://localhost:8501

RATE_LIMIT_WINDOW_SECONDS=60
RATE_LIMIT_MAX_REQUESTS=120

ALLOW_PUBLIC_REGISTRATION=false
INTERNAL_TRANSLATION_PROVIDER=nllb
ALLOW_INTERNAL_DEMO_TRANSLATION=false
INTERNAL_SUPPORTED_LANGUAGES=bn:Bengali,ar:Arabic,hi:Hindi,es:Spanish,fr:French,de:German,en:English

TRANSLATION_PROVIDER=demo
NLLB_TRANSLATION_URL=
NLLB_HEALTH_URL=
NLLB_TRANSLATION_MODEL=nllb-200
OPENAI_API_KEY=
OPENAI_TRANSLATION_MODEL=gpt-4.1-mini
OPENAI_BASE_URL=https://api.openai.com/v1
GEMINI_API_KEY=
GEMINI_TRANSLATION_MODEL=gemini-3.5-flash
GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta
LIBRETRANSLATE_URL=http://127.0.0.1:5000
LIBRETRANSLATE_API_KEY=
TRANSLATION_TIMEOUT_SECONDS=20

SPEECH_TO_TEXT_PROVIDER=demo
SPEECH_TO_TEXT_URL=
TEXT_TO_SPEECH_PROVIDER=demo
TEXT_TO_SPEECH_URL=
SPEECH_TIMEOUT_SECONDS=30

WEBHOOK_TIMEOUT_SECONDS=10
```

Important production values:

- `APP_ENV=production`
- `SECRET_KEY`: set a long random value.
- `DATABASE_URL`: use PostgreSQL. All application data should live in PostgreSQL.
- `CORS_ORIGINS`: restrict to your deployed frontend domain.
- Provider keys: set only on the Translator App server.
- `ALLOW_PUBLIC_REGISTRATION=false` for internal-only access.
- Create admin users with `python -m backend.manage create-admin --username admin`, not `.env`.

## Provider Setup

### Demo Provider

Demo mode is safe for development and does not call any paid provider:

```env
TRANSLATION_PROVIDER=demo
```

Example output:

```text
[Demo translation: Hello (en -> es)]
```

### NLLB Provider

Use NLLB when you have a private NLLB translation service already running.

```env
TRANSLATION_PROVIDER=nllb
NLLB_TRANSLATION_URL=http://127.0.0.1:9000/translate
NLLB_TRANSLATION_MODEL=nllb-200
```

Translator App sends JSON like this to `NLLB_TRANSLATION_URL`:

```json
{
  "text": "Hello world",
  "source_language": "en",
  "target_language": "bn",
  "source": "en",
  "target": "bn",
  "model": "nllb-200"
}
```

Your NLLB service should return one of these fields:

```json
{
  "translated_text": "..."
}
```

Accepted response keys are:

- `translated_text`
- `translatedText`
- `translation`
- `text`
- `output`

### OpenAI Provider

Set your OpenAI key only on the Translator App server:

```env
TRANSLATION_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_TRANSLATION_MODEL=gpt-4.1-mini
OPENAI_BASE_URL=https://api.openai.com/v1
```

Translator App uses the OpenAI Responses API and sends:

```json
{
  "model": "gpt-4.1-mini",
  "instructions": "Translate the user's content...",
  "input": "Hello world"
}
```

The provider may return exact token usage. Translator App stores that in usage logs when available.

### Gemini Provider

Set your Gemini key only on the Translator App server:

```env
TRANSLATION_PROVIDER=gemini
GEMINI_API_KEY=...
GEMINI_TRANSLATION_MODEL=gemini-3.5-flash
GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta
```

Translator App calls:

```text
POST /models/{model}:generateContent
```

It sends a translation instruction as `system_instruction` and the user text in `contents`.

### LibreTranslate Provider

Use a LibreTranslate-compatible server:
### Running LibreTranslate Locally With Docker

Start the LibreTranslate container with only the languages you need:

```bash
docker run -ti -p 5000:5000 libretranslate/libretranslate --load-only en,es,fr,de,ar,bn,zh,hi,it,pt
```

This downloads and starts a local LibreTranslate server on port 5000. The `--load-only` flag limits which language models are loaded, keeping startup fast and memory usage low. The container must be running before you start the backend.

For a detached (background) run:

```bash
docker run -d -p 5000:5000 libretranslate/libretranslate --load-only en,es,fr,de,ar,bn,zh,hi,it,pt
```
```env
TRANSLATION_PROVIDER=libretranslate
LIBRETRANSLATE_URL=http://127.0.0.1:5000
LIBRETRANSLATE_API_KEY=
```

Translator App calls:

```text
POST {LIBRETRANSLATE_URL}/translate
```

### Per-Request Provider Selection

Admins can configure a server default in `.env`, and users/integration clients can override it per request:

```json
{
  "text": "Hello world",
  "source_language": "en",
  "target_language": "bn",
  "provider": "openai",
  "model": "gpt-4.1-mini"
}
```

Supported `provider` values:

```text
nllb
openai
gemini
libretranslate
demo
```

Leave `provider` and `model` blank to use the server default.

## Admin Workflow

1. Start Translator App backend and frontend.
2. Confirm `DATABASE_URL` points to PostgreSQL.
3. Create the first admin in PostgreSQL:

```powershell
python -m backend.manage create-admin --username admin
```

4. Login to Streamlit with that admin account.
5. Open `Admin Users`.
6. Create internal user accounts.
7. Configure NLLB/provider settings in `.env`.
8. Restart backend after changing `.env`.
9. Open `Internal Usage` to monitor staff activity.
10. Optional: open `Integrations` to create external client API keys.
11. Create an integration for an external client:

```text
Name: Main WordPress Site
Platform: wordpress
Site URL: https://example.com
Webhook URL: optional
```

12. Copy the generated API key immediately. It is shown only once.
13. Give the external platform only this Translator App API key.
14. Monitor external usage from `Admin Usage`.

The admin should not share provider keys with clients. Clients only use the Translator App key.

## User Workflow

1. Login to Streamlit.
2. Open `Internal Translate`.
3. Choose source and target language.
4. Enter source text on the left.
5. Click `Translate`.
6. Read the translated output on the right.
7. Open `Documents` to upload `.docx` or `.txt` and download translated files.
8. Open `Excel` to upload `.xlsx`, choose columns, choose target languages, and download an output workbook with appended translated columns.
9. Open `My History` to search, export, or delete text translation history.

## Integration API

Base URL:

```text
https://your-translator-app-domain.com
```

Local URL:

```text
http://127.0.0.1:8000
```

### Integration Authentication

External platforms authenticate with an integration API key:

```http
X-API-Key: trn_xxxxxxxx_secret
```

Alternative:

```http
Authorization: Bearer trn_xxxxxxxx_secret
```

Do not use user JWTs in external CMS plugins. Use integration API keys.

### Create Integration Key

Admins can create integrations in the UI or with the admin API:

```http
POST /api/admin/integrations
Authorization: Bearer <admin-jwt>
Content-Type: application/json

{
  "name": "Main WordPress Site",
  "platform": "wordpress",
  "site_url": "https://example.com",
  "webhook_url": "https://example.com/translator-app/webhook"
}
```

Response includes:

```json
{
  "id": 1,
  "name": "Main WordPress Site",
  "platform": "wordpress",
  "api_key": "trn_xxxxxxxx_secret",
  "message": "Store this API key now. It will not be shown again."
}
```

### Core Endpoints

```http
GET  /api/v1/languages
GET  /api/v1/integration
GET  /api/v1/usage
POST /api/v1/translate
POST /api/v1/translate/html
POST /api/v1/translate/batch
GET  /api/v1/jobs/{job_id}
POST /api/v1/content/sync
GET  /api/v1/content
GET  /api/v1/content/{content_id}
POST /api/v1/content/{content_id}/publish
```

### Translate Plain Text

```http
POST /api/v1/translate
X-API-Key: trn_xxxxxxxx_secret
Content-Type: application/json
```

```json
{
  "text": "Hello world",
  "source_language": "en",
  "target_language": "bn",
  "format": "text",
  "provider": "openai",
  "model": "gpt-4.1-mini"
}
```

Response:

```json
{
  "translated_text": "...",
  "provider": "openai",
  "translation_model": "gpt-4.1-mini",
  "usage_tokens": 42,
  "demo_mode": false,
  "format": "text",
  "content": null
}
```

### Translate HTML

Use this for CMS posts, pages, blocks, product descriptions, and rich text.

```http
POST /api/v1/translate/html
X-API-Key: trn_xxxxxxxx_secret
Content-Type: application/json
```

```json
{
  "external_content_id": "wp-post-123",
  "content_type": "post",
  "title": "Hello world",
  "source_language": "en",
  "target_language": "bn",
  "format": "html",
  "provider": "gemini",
  "model": "gemini-3.5-flash",
  "text": "<p>Hello <strong>world</strong> [gallery ids=\"1,2\"]</p>",
  "metadata": {
    "wordpress_post_id": 123
  }
}
```

HTML translation preserves:

- HTML tags
- shortcode blocks such as `[gallery ids="1,2"]`
- links
- scripts
- styles
- `code`, `pre`, and `textarea` contents

### Batch Translation

Use batch translation for many posts/pages/items.

```http
POST /api/v1/translate/batch
X-API-Key: trn_xxxxxxxx_secret
Content-Type: application/json
```

```json
{
  "source_language": "en",
  "target_language": "bn",
  "provider": "openai",
  "model": "gpt-4.1-mini",
  "callback_url": "https://example.com/translator-app/webhook",
  "items": [
    {
      "external_content_id": "post-123",
      "content_type": "post",
      "title": "Hello",
      "format": "html",
      "text": "<p>Hello world</p>"
    },
    {
      "external_content_id": "page-50",
      "content_type": "page",
      "title": "About",
      "format": "html",
      "provider": "gemini",
      "model": "gemini-3.5-flash",
      "text": "<p>About us</p>"
    }
  ]
}
```

Batch-level `provider` and `model` apply to all items unless an item overrides them.

### Job Status

```http
GET /api/v1/jobs/{job_id}
X-API-Key: trn_xxxxxxxx_secret
```

Response:

```json
{
  "id": 10,
  "status": "completed",
  "source_language": "en",
  "target_language": "bn",
  "item_count": 2,
  "completed_count": 2,
  "error": null,
  "result": []
}
```

### Content Sync

Use this when you want Translator App to know about external content before translating it.

```http
POST /api/v1/content/sync
X-API-Key: trn_xxxxxxxx_secret
Content-Type: application/json
```

```json
{
  "external_content_id": "article-123",
  "content_type": "article",
  "title": "Hello",
  "source_language": "en",
  "target_language": "bn",
  "format": "html",
  "text": "<p>Hello world</p>",
  "metadata": {
    "source_url": "https://example.com/article-123"
  }
}
```

### Publish Event

```http
POST /api/v1/content/{content_id}/publish
X-API-Key: trn_xxxxxxxx_secret
Content-Type: application/json
```

```json
{
  "status": "ready"
}
```

Translator App sends a webhook to the integration webhook URL when configured.

### Webhook Payloads

Batch completed:

```json
{
  "event": "translation.completed",
  "job": {
    "id": 10,
    "status": "completed"
  }
}
```

Content ready:

```json
{
  "event": "content.ready_to_publish",
  "content": {
    "id": 1,
    "external_content_id": "post-123",
    "translated_text": "..."
  },
  "publish_payload": {
    "external_content_id": "post-123",
    "content_type": "post",
    "title": "Hello",
    "target_language": "bn",
    "format": "html",
    "translated_text": "..."
  }
}
```

### Common API Errors

```json
{
  "detail": "Integration API key is required"
}
```

```json
{
  "detail": "Invalid integration API key"
}
```

```json
{
  "detail": "OPENAI_API_KEY is required when translation provider is openai"
}
```

```json
{
  "detail": "GEMINI_API_KEY is required when translation provider is gemini"
}
```

```json
{
  "detail": "NLLB_TRANSLATION_URL is required when translation provider is nllb"
}
```

## WordPress Integration

Connector path:

```text
connectors/wordpress/translator-app
```

The WordPress connector is a WordPress admin plugin. It sends WordPress content to Translator App through the external integration API and receives translated HTML back.

The plugin can:

- translate posts, pages, and supported custom post types
- translate title, excerpt, and post HTML content
- create or update a real translated WordPress post
- keep translated posts as draft/pending review/private/published
- store translated snapshots in WordPress post meta
- run bulk translation from list tables
- connect translations to Polylang or WPML when installed
- use NLLB, OpenAI, Gemini, LibreTranslate, or the server default provider

Important security rule:

```text
WordPress stores only the Translator App integration API key.
OpenAI, Gemini, NLLB, LibreTranslate, and other provider secrets stay on the Translator App server.
```

### WordPress Requirements

- WordPress with admin access.
- Translator App backend running and reachable from the WordPress server.
- A Translator App admin account.
- A Translator App integration record for the WordPress site.
- Optional: Polylang or WPML if you want WordPress-native multilingual links.

### WordPress Step 1: Create The Integration In Translator App

1. Log in to Translator App as admin.
2. Open the integrations/admin area.
3. Create a new integration:

```text
Name: Main WordPress Site
Platform: wordpress
Site URL: https://your-wordpress-site.com
Webhook URL: optional
```

4. Save the integration.
5. Copy the generated API key.

The key should look like:

```text
trn_xxxxxxxx_secret
```

Use this key only inside WordPress `Settings -> Translator App`.

### WordPress Step 2: Install The Plugin

Copy the plugin folder:

```text
connectors/wordpress/translator-app
```

to:

```text
wp-content/plugins/translator-app
```

The final WordPress path should be:

```text
wp-content/plugins/translator-app/translator-app.php
```

Then:

1. Open WordPress admin.
2. Go to:

```text
Plugins -> Installed Plugins
```

3. Activate:

```text
Translator App
```

### WordPress Step 3: Configure Plugin Settings

Open:

```text
Settings -> Translator App
```

Configure:

```text
API Base URL: https://your-translator-app-domain.com
API Key: trn_xxxxxxxx_secret
Source Language: en
Target Language: bn
Translation Provider: Server default / NLLB / OpenAI / Gemini / LibreTranslate / Demo
Model Override: optional
Output Mode: Create or update translated post
Translated Post Status: Draft / Pending review / Private / Publish / Same as source post
Language Plugin: Auto-detect WPML or Polylang
```

Recommended first setup:

```text
Translation Provider: Server default
Output Mode: Create or update translated post
Translated Post Status: Draft
Language Plugin: Auto-detect WPML or Polylang
Translate title: enabled
Translate excerpt: enabled
Copy featured image: enabled
```

Field meaning:

| Setting | Meaning |
| --- | --- |
| API Base URL | Public URL of your Translator App backend, without a trailing slash. |
| API Key | The `trn_...` integration key generated by Translator App. |
| Source Language | Source language code, for example `en`. |
| Target Language | Target language code, for example `bn`, `es`, `fr`, `ar`. |
| Translation Provider | Leave as `Server default` unless this site should force `nllb`, `openai`, `gemini`, or `libretranslate`. |
| Model Override | Optional model name. Leave blank for the server default. |
| Output Mode | Choose whether to create translated posts or only store translated HTML in meta. |
| Translated Post Status | Use `Draft` or `Pending review` until the workflow is tested. |
| Language Plugin | Auto-detects Polylang/WPML or disables multilingual linking. |

### WordPress Step 4: Translate One Post

1. Open:

```text
Posts -> All Posts
```

2. Edit a post.
3. In the publish/sidebar area, click:

```text
Translate with Translator App
```

4. Translator App translates title, excerpt, and content.
5. WordPress creates or updates the translated post.
6. Open the translated post from the `Translator App` side panel.
7. Review formatting, links, images, shortcodes, and SEO fields.
8. Publish when ready.

### WordPress Output Modes

`Create or update translated post`

This is the recommended mode. The plugin creates a second WordPress post/page/custom post type entry for the target language. If a translated post already exists for that source post and target language, the plugin updates it instead of creating a duplicate.

`Store translated HTML in post meta only`

This mode does not create a public translated post. It stores translation data in post meta so a developer can use a custom publishing workflow.

### WordPress Bulk Translation

1. Open a WordPress list table such as:

```text
Posts -> All Posts
```

or:

```text
Pages -> All Pages
```

2. Select one or more posts/pages.
3. Choose:

```text
Bulk actions -> Translate with Translator App
```

4. Click `Apply`.

The plugin translates each selected item using the configured source/target language and output mode.

Recommended bulk workflow:

1. Set `Translated Post Status` to `Draft`.
2. Translate a small batch first.
3. Review the translated posts.
4. Then translate larger batches.

For very large WordPress sites, batch a small number of posts at a time unless the Translator App provider and server timeout are tuned for larger loads.

### WordPress Polylang Integration

If Polylang is installed and `Language Plugin` is `Auto-detect WPML or Polylang` or `Polylang`, the plugin calls:

```php
pll_set_post_language()
pll_save_post_translations()
```

Expected behavior:

- source post language is set or reused
- translated post language is set to the target language
- source and translated posts are linked in Polylang translations

Polylang checklist:

1. Install and configure Polylang.
2. Add the target language in Polylang.
3. Confirm the language code matches Translator App, for example `bn`, `es`, `fr`.
4. Set `Language Plugin` to `Auto-detect WPML or Polylang`.
5. Translate one post and confirm the Polylang language switcher sees the translation.

### WordPress WPML Integration

If WPML is installed and `Language Plugin` is `Auto-detect WPML or Polylang` or `WPML`, the plugin uses:

```php
wpml_element_type
wpml_element_language_details
wpml_set_element_language_details
```

Expected behavior:

- translated post is assigned the target language
- translated post is connected to the source post translation group
- WPML can show the translated item in its translation relationships

WPML checklist:

1. Install and configure WPML.
2. Add the target language in WPML.
3. Confirm the language code matches Translator App.
4. Set `Language Plugin` to `Auto-detect WPML or Polylang`.
5. Translate one post and verify WPML links it to the source post.

### WordPress What Gets Copied

The plugin copies:

- translated title
- translated excerpt
- translated HTML content
- source post type
- source post author
- parent post
- menu order
- comment/ping status
- featured image, if enabled
- page template, if present
- public taxonomies, such as categories and tags

The plugin does not automatically copy all custom fields. Many WordPress sites store page-builder data, SEO plugin data, product data, or serialized settings in custom fields. Copying all meta blindly can break layouts or duplicate plugin state. Add custom meta mapping only after reviewing the site structure.

### WordPress Request Flow

The plugin calls:

```text
POST /api/v1/translate/html
```

Payload includes:

```json
{
  "external_content_id": "wp-post-123-content",
  "content_type": "post",
  "title": "Post title",
  "source_language": "en",
  "target_language": "bn",
  "format": "html",
  "provider": "openai",
  "model": "gpt-4.1-mini",
  "text": "<p>Post HTML</p>",
  "metadata": {
    "wordpress_post_id": 123,
    "wordpress_post_status": "draft"
  }
}
```

### WordPress Output

By default, the plugin creates or updates a translated post and links it from the source post. The translated post receives:

```text
_translator_app_source_post_id
_translator_app_source_language
_translator_app_target_language
_translator_app_language_plugin
```

The source post stores the target-language to translated-post mapping:

```text
_translator_app_translation_post_ids
```

The plugin also stores translated content snapshots in post meta:

```text
_translator_app_translations
```

The meta value is an array keyed by target language:

```php
[
    'bn' => [
        'content' => '<p>Translated HTML</p>',
        'title' => 'Translated title',
        'excerpt' => 'Translated excerpt',
        'provider' => 'nllb',
        'translation_model' => 'server-default',
        'updated_at' => '2026-06-15 10:30:00',
    ],
]
```

If Polylang is installed, the plugin calls:

```php
pll_set_post_language()
pll_save_post_translations()
```

If WPML is installed, the plugin uses:

```php
wpml_element_type
wpml_element_language_details
wpml_set_element_language_details
```

### WordPress Troubleshooting

`Translator App API URL and key are required.`

Check:

```text
Settings -> Translator App -> API Base URL
Settings -> Translator App -> API Key
```

`Translator App API request failed.`

Check:

- Translator App backend is running.
- WordPress server can reach the Translator App URL.
- Integration API key is active.
- Provider is configured on the Translator App server.
- NLLB URL/API keys are configured on the Translator App server, not in WordPress.

Translated post was created but not linked in Polylang/WPML:

- Confirm Polylang or WPML is active.
- Confirm the target language exists in the multilingual plugin.
- Confirm language code matches exactly.
- Set `Language Plugin` to the specific plugin instead of `Auto-detect`.

Translated content appears only in meta:

- Set `Output Mode` to `Create or update translated post`.
- Open the source post editor and check the `Translator App` side panel.

### WordPress Production Notes

- Keep `Translated Post Status` as `Draft` or `Pending review` until your editorial workflow is tested.
- The plugin copies featured image, page template, public taxonomies, title, excerpt, and HTML content.
- Custom field copying is intentionally not automatic because sites often store builder/layout/plugin data in post meta.
- Use `Output Mode: Store translated HTML in post meta only` if you want a fully custom publishing workflow.
- Keep the Translator App API key in WordPress settings only.
- Do not store OpenAI/Gemini provider keys in WordPress.

## Drupal Integration

Connector path:

```text
connectors/drupal/translator_app
```

The Drupal connector is a Drupal custom module. It can run in two modes:

| Mode | Purpose | Recommended for production |
| --- | --- | --- |
| Standalone route | Quick test/manual translation preview for a node body. | No |
| TMGMT provider | Full Drupal Translation Management Tool workflow. | Yes |

For TMGMT, Drupal handles source selection, jobs, review, acceptance, and writing accepted translations back through Drupal's translation system. Translator App acts as the translation provider.

Important security rule:

```text
Drupal stores only the Translator App integration API key.
OpenAI, Gemini, NLLB, LibreTranslate, and other provider secrets stay on the Translator App server.
```

### Drupal Requirements

- Drupal 10 or Drupal 11.
- Admin access to Drupal.
- Translator App backend running and reachable from the Drupal server.
- A Translator App admin account.
- A Translator App integration record for the Drupal site.
- Optional but recommended: TMGMT.
- For content write-back: Drupal Content Translation enabled and configured.

### Drupal Step 1: Create The Integration In Translator App

1. Log in to Translator App as admin.
2. Open the integrations/admin area.
3. Create a new integration:

```text
Name: Main Drupal Site
Platform: drupal
Site URL: https://your-drupal-site.com
Webhook URL: optional
```

4. Save the integration.
5. Copy the generated API key:

```text
trn_xxxxxxxx_secret
```

### Drupal Step 2: Install The Module

Copy the module folder:

```text
connectors/drupal/translator_app
```

to:

```text
web/modules/custom/translator_app
```

or:

```text
modules/custom/translator_app
```

depending on your Drupal project structure.

The final Drupal path should be:

```text
web/modules/custom/translator_app/translator_app.info.yml
```

or:

```text
modules/custom/translator_app/translator_app.info.yml
```

Enable the module:

```bash
drush en translator_app -y
```

Or enable it from:

```text
Extend -> Translator App
```

### Drupal Step 3: Configure Standalone Module Settings

Open:

```text
/admin/config/services/translator-app
```

Configure:

```text
API base URL: https://your-translator-app-domain.com
API key: trn_xxxxxxxx_secret
Source language: en
Target language: bn
Translation provider: Server default / NLLB / OpenAI / Gemini / LibreTranslate / Demo
Model override: optional
```

These settings are used by the standalone route and can also be used as fallback values by the TMGMT provider.

### Drupal Standalone Translation Test

Use this mode only to confirm the API is reachable.

Route:

```text
/admin/config/services/translator-app/translate-node/{node}
```

Example:

```text
/admin/config/services/translator-app/translate-node/123
```

What happens:

- Drupal loads the node body field.
- Drupal sends body HTML to Translator App.
- Translator App returns translated HTML.
- Drupal displays the translated HTML on an admin page.

This standalone route does not save translated content into the node. Use TMGMT for Drupal-native write-back.

### Drupal TMGMT Step 1: Install TMGMT

Install TMGMT with Composer:

```bash
composer require drupal/tmgmt
```

Enable the required modules:

```bash
drush en tmgmt tmgmt_content content_translation translator_app -y
```

Common optional source modules:

```bash
drush en tmgmt_config tmgmt_locale -y
```

Use them if you want to translate configuration or interface strings.

### Drupal TMGMT Step 2: Enable Content Translation

For nodes:

1. Open:

```text
Configuration -> Regional and language -> Content language and translation
```

2. Enable translation for the content types you want to translate.
3. Enable the fields that should be translatable.
4. Save configuration.

For a normal article/page workflow, make sure fields such as title, body, summary, and SEO fields are configured as translatable as needed.

### Drupal TMGMT Step 3: Add Translator App As A Provider

Open:

```text
Translation -> Providers
```

Add a provider:

```text
Label: Translator App
Provider plugin: Translator App
Translator App API base URL: https://your-translator-app-domain.com
Translator App API key: trn_xxxxxxxx_secret
Translation provider: Server default / NLLB / OpenAI / Gemini / LibreTranslate / Demo
Model override: optional
Use HTML-safe translation: enabled
Request timeout seconds: 90
```

Recommended first setup:

```text
Translation provider: Server default
Model override: blank
Use HTML-safe translation: enabled
Auto accept finished translations: disabled
```

Keep `Auto accept finished translations` disabled until you trust the translation quality and field behavior.

### Drupal TMGMT Step 4: Request Translation

Open:

```text
Translation -> Sources
```

Typical content workflow:

1. Select the source type, such as content/node.
2. Filter to the content you want to translate.
3. Select one or more items.
4. Click:

```text
Request translation
```

5. Choose target language(s).
6. Select provider:

```text
Translator App
```

7. Submit the job.
8. Wait for the translated data to return.
9. Review translations in TMGMT.
10. Accept the translations.

When accepted, TMGMT writes the translation back through its source plugin, usually Drupal Content Translation for content entities.

### Drupal TMGMT Step 5: Review And Publish

After Translator App returns translated data:

1. Open the TMGMT job.
2. Review each translated item.
3. Edit translated fields if needed.
4. Accept the job item.
5. Check the translated node/entity.
6. Publish according to your Drupal editorial workflow.

### Drupal TMGMT Request Flow

The provider submits each translatable TMGMT data item to:

```text
POST /api/v1/translate/html
```

or, when HTML-safe mode is disabled and the source is plain text:

```text
POST /api/v1/translate
```

Payload shape:

```json
{
  "external_content_id": "drupal-tmgmt-job-42-item-99-abc123",
  "content_type": "tmgmt:content:node",
  "title": "Job label",
  "source_language": "en",
  "target_language": "bn",
  "format": "html",
  "text": "<p>Drupal field HTML</p>",
  "metadata": {
    "drupal_tmgmt_job_id": 42,
    "drupal_tmgmt_job_item_id": 99,
    "drupal_tmgmt_item_type": "node",
    "drupal_tmgmt_item_id": "123",
    "drupal_tmgmt_data_key": "body][0][value"
  }
}
```

It returns translated data to TMGMT using:

```php
$job_item->addTranslatedData(...)
```

### Drupal Output

Standalone route output:

- displays translated HTML on a Drupal admin page
- does not write directly to node fields

TMGMT output:

- creates TMGMT translated data items
- supports TMGMT review
- writes accepted translations back through Drupal/TMGMT source plugins
- works with Drupal Content Translation when TMGMT content source is configured

### Drupal Troubleshooting

Provider plugin does not appear in TMGMT:

- Confirm `translator_app` module is enabled.
- Confirm `tmgmt` module is enabled.
- Clear Drupal caches:

```bash
drush cr
```

API request fails:

- Confirm API base URL is reachable from the Drupal server.
- Confirm API key is the Translator App integration key.
- Confirm the integration is active in Translator App.
- Confirm provider settings are configured on the Translator App server.

Translation returns but does not write to node:

- Use the TMGMT provider, not the standalone route.
- Confirm Drupal Content Translation is enabled.
- Confirm the content type and fields are translatable.
- Review and accept the TMGMT job item.

HTML tags look broken:

- Keep `Use HTML-safe translation` enabled.
- Confirm your source text format allows the returned tags.
- Review custom filters that may strip translated HTML.

### Drupal Production Notes

- Store only the Translator App API key in Drupal config.
- Do not store OpenAI/Gemini provider keys in Drupal.
- For production, prefer the TMGMT provider over the standalone preview route.
- Keep `Auto accept finished translations` disabled until your review workflow is proven.
- Restrict route permissions before production if editors should translate but not administer the whole site.
- Use Drupal Queue/cron or TMGMT continuous jobs for large content sets.

## Django Integration

Connector path:

```text
connectors/django/translator_client
```

The Django connector is a small Python client. Copy it into your Django app or package it internally.

### Django Install

1. Copy:

```text
connectors/django/translator_client
```

into your Django project, for example:

```text
my_project/translator_client
```

2. Add settings:

```python
TRANSLATOR_APP_API_BASE_URL = "https://your-translator-app-domain.com"
TRANSLATOR_APP_API_KEY = "trn_xxxxxxxx_secret"
TRANSLATOR_APP_DEFAULT_SOURCE_LANGUAGE = "en"
TRANSLATOR_APP_DEFAULT_TARGET_LANGUAGE = "bn"
TRANSLATOR_APP_TRANSLATION_PROVIDER = "openai"
TRANSLATOR_APP_TRANSLATION_MODEL = "gpt-4.1-mini"
```

3. Create an integration in Translator App admin:

```text
Platform: django
Site URL: https://your-django-site.com
```

4. Put the generated Translator App API key in Django settings or environment variables.

### Django Basic Usage

```python
from django.conf import settings
from translator_client import TranslatorClient

client = TranslatorClient(
    base_url=settings.TRANSLATOR_APP_API_BASE_URL,
    api_key=settings.TRANSLATOR_APP_API_KEY,
)

result = client.translate(
    text="<p>Hello world</p>",
    source_language=settings.TRANSLATOR_APP_DEFAULT_SOURCE_LANGUAGE,
    target_language=settings.TRANSLATOR_APP_DEFAULT_TARGET_LANGUAGE,
    content_format="html",
    provider=settings.TRANSLATOR_APP_TRANSLATION_PROVIDER,
    model=settings.TRANSLATOR_APP_TRANSLATION_MODEL,
    external_content_id="article-123",
    content_type="article",
    title="Hello world",
)

translated_html = result["translated_text"]
```

### Django Model Example

```python
from django.db import models

class Article(models.Model):
    title = models.CharField(max_length=255)
    body_html = models.TextField()
    translated_body_html = models.TextField(blank=True)
    translated_language = models.CharField(max_length=10, blank=True)
```

### Django Service Example

```python
from django.conf import settings
from translator_client import TranslatorClient

def translate_article(article, target_language="bn"):
    client = TranslatorClient(
        base_url=settings.TRANSLATOR_APP_API_BASE_URL,
        api_key=settings.TRANSLATOR_APP_API_KEY,
    )

    result = client.translate(
        text=article.body_html,
        source_language="en",
        target_language=target_language,
        content_format="html",
        provider=getattr(settings, "TRANSLATOR_APP_TRANSLATION_PROVIDER", None),
        model=getattr(settings, "TRANSLATOR_APP_TRANSLATION_MODEL", None),
        external_content_id=f"article-{article.pk}",
        content_type="article",
        title=article.title,
        metadata={
            "django_model": "Article",
            "django_pk": article.pk,
        },
    )

    article.translated_body_html = result["translated_text"]
    article.translated_language = target_language
    article.save(update_fields=["translated_body_html", "translated_language"])
    return result
```

### Django Batch Example

```python
items = [
    {
        "external_content_id": f"article-{article.pk}",
        "content_type": "article",
        "title": article.title,
        "format": "html",
        "text": article.body_html,
        "metadata": {"django_pk": article.pk},
    }
    for article in articles
]

job = client.translate_batch(
    items=items,
    source_language="en",
    target_language="bn",
    provider="openai",
    model="gpt-4.1-mini",
    callback_url="https://your-django-site.com/webhooks/translator-app/",
)
```

### Django Webhook View Example

```python
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

@csrf_exempt
def translator_app_webhook(request):
    payload = json.loads(request.body.decode("utf-8"))
    event = payload.get("event")

    if event == "translation.completed":
        job = payload.get("job", {})
        # Fetch job result or update local status here.

    if event == "content.ready_to_publish":
        content = payload.get("content", {})
        # Save translated content to the matching model here.

    return JsonResponse({"ok": True})
```

### Django Production Notes

- Store the Translator App API key in environment variables or a secret manager.
- Do not put provider keys in Django.
- Use Celery/RQ/background jobs for large translation batches.
- Validate webhook payloads before automatic publishing.

## Custom Platform Integration

Any platform can integrate with Translator App using HTTP.

### Minimal cURL Example

```bash
curl -X POST "https://your-translator-app-domain.com/api/v1/translate" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: trn_xxxxxxxx_secret" \
  -d '{
    "text": "Hello world",
    "source_language": "en",
    "target_language": "bn",
    "format": "text",
    "provider": "openai",
    "model": "gpt-4.1-mini"
  }'
```

### HTML cURL Example

```bash
curl -X POST "https://your-translator-app-domain.com/api/v1/translate/html" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: trn_xxxxxxxx_secret" \
  -d '{
    "external_content_id": "product-123",
    "content_type": "product",
    "title": "Blue shirt",
    "source_language": "en",
    "target_language": "bn",
    "format": "html",
    "text": "<p>Comfortable cotton shirt.</p>",
    "metadata": {
      "product_id": 123,
      "source_url": "https://shop.example.com/products/123"
    }
  }'
```

### JavaScript Fetch Example

```js
async function translateWithTranslatorApp() {
  const response = await fetch("https://your-translator-app-domain.com/api/v1/translate/html", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": "trn_xxxxxxxx_secret",
    },
    body: JSON.stringify({
      external_content_id: "page-123",
      content_type: "page",
      title: "About us",
      source_language: "en",
      target_language: "bn",
      format: "html",
      provider: "gemini",
      model: "gemini-3.5-flash",
      text: "<p>About our company</p>",
    }),
  });

  if (!response.ok) {
    throw new Error(await response.text());
  }

  return response.json();
}
```

Do not expose the Translator App API key in public browser code. Use this JavaScript pattern only in server-side code or private admin tools.

## Usage And Token Reporting

Admins can view external/client usage in the Streamlit `Admin Usage` page.

Admins can view internal-user usage in the Streamlit `Internal Usage` page.

Admin API endpoints:

```http
GET /api/admin/usage/summary?group_by=integration
GET /api/admin/usage/summary?group_by=user
GET /api/admin/usage/summary?group_by=provider
GET /api/admin/usage/logs
```

Internal usage endpoints:

```http
GET /api/internal/admin/usage/summary
GET /api/internal/admin/activities
GET /api/internal/admin/activities?user_id=1
GET /api/internal/admin/activities?activity_type=document
```

Internal usage includes:

- text translation count
- documents uploaded
- Excel files uploaded
- Excel rows translated
- character usage
- source filename
- output/download filename
- timestamp

Integration-specific usage:

```http
GET /api/v1/usage
X-API-Key: trn_xxxxxxxx_secret
```

Usage log fields:

```json
{
  "id": 1,
  "user_id": null,
  "integration_id": 1,
  "actor_type": "integration",
  "route": "/api/v1/translate/html",
  "provider": "openai",
  "model_type": "integration:html:gpt-4.1-mini",
  "source_language": "en",
  "target_language": "bn",
  "character_count": 1200,
  "estimated_tokens": 300,
  "created_at": "2026-06-15T12:00:00"
}
```

Token behavior:

- OpenAI and Gemini can return provider token totals.
- Translator App stores provider-reported totals when available.
- Other providers fall back to an estimate of roughly one token per four characters.

## Docker

Copy env:

```powershell
Copy-Item .env.example .env
```

Run:

```powershell
docker compose up --build
```

Create the first admin in the PostgreSQL database:

```powershell
docker compose exec backend python -m backend.manage create-admin --username admin
```

Frontend:

```text
http://127.0.0.1:8501
```

Backend:

```text
http://127.0.0.1:8000/api/health
```

## Production Checklist

- Set `APP_ENV=production`.
- Set a strong permanent `SECRET_KEY`.
- Use PostgreSQL via `DATABASE_URL`.
- Store users, admins, API key hashes, integrations, usage, history, document activity, and Excel activity in PostgreSQL.
- Do not store admin credentials in `.env`.
- Create or reset admin accounts with `python -m backend.manage create-admin --username admin`.
- Restrict `CORS_ORIGINS`.
- Use HTTPS for the frontend and backend.
- Put provider keys in server environment variables or a secret manager.
- Never send provider keys to clients.
- Rotate integration API keys if exposed.
- Tune `RATE_LIMIT_WINDOW_SECONDS` and `RATE_LIMIT_MAX_REQUESTS`.
- Configure logging and backups.
- Put Streamlit/FastAPI behind a reverse proxy.
- Use a process manager or container orchestrator.
- Replace demo providers before real customer usage.
- Add webhook verification before fully automated publishing.

## Troubleshooting

### Translation is in demo mode

Check:

```env
TRANSLATION_PROVIDER=demo
```

Set it to a real provider and restart the backend.

### OpenAI requests fail

Check:

```env
OPENAI_API_KEY=
OPENAI_TRANSLATION_MODEL=gpt-4.1-mini
OPENAI_BASE_URL=https://api.openai.com/v1
```

Then restart FastAPI.

### Gemini requests fail

Check:

```env
GEMINI_API_KEY=
GEMINI_TRANSLATION_MODEL=gemini-3.5-flash
GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta
```

Then restart FastAPI.

### NLLB requests fail

Check:

```env
NLLB_TRANSLATION_URL=http://127.0.0.1:9000/translate
NLLB_TRANSLATION_MODEL=nllb-200
```

Confirm the NLLB service accepts the JSON contract described above.

### Client receives invalid API key

Check:

- The client is using `X-API-Key`.
- The key starts with `trn_`.
- The integration is active in Translator App admin.
- The key was not rotated after the client was configured.

### HTML output loses formatting

Use:

```text
POST /api/v1/translate/html
```

not:

```text
POST /api/v1/translate
```

HTML mode preserves tags and shortcodes.

### WordPress translation does not appear on the public page

Check `Settings -> Translator App`.

If `Output Mode` is:

```text
Store translated HTML in post meta only
```

the translated content is stored in:

```text
_translator_app_translations
```

If `Output Mode` is:

```text
Create or update translated post
```

open the source post editor and check the `Translator App` side panel for the translated post link. If you use WPML or Polylang, also confirm the target language code exists in that plugin.

### Drupal translation does not save to node

The standalone Drupal route displays translated HTML only.

For write-back into Drupal translations, use the TMGMT provider:

```text
Translation -> Providers -> Add provider -> Translator App
```

Then request translation through:

```text
Translation -> Sources
```

## Current Limits And Upgrade Roadmap

Already implemented:

- User auth and admin users.
- Internal-only portal pages.
- Admin-created internal users.
- PostgreSQL-backed first-admin creation command.
- Public registration disable switch.
- Local NLLB-first internal translation with clear missing-provider errors.
- Internal text translation UI.
- `.docx` and `.txt` document translation.
- `.xlsx` selected-column translation with appended translated columns.
- Internal usage and download/activity history.
- Internal provider health endpoint.
- Configurable internal supported languages endpoint.
- Provider selection for NLLB, OpenAI, Gemini, LibreTranslate, and demo.
- PostgreSQL storage for users, admins, API key hashes, integrations, usage, history, and internal activity.
- Server-side provider runtime settings through environment variables or a secret manager.
- Integration API keys.
- HTML-safe translation.
- Batch translation.
- Webhooks.
- Usage and token reporting.
- WordPress connector with translated post creation/update, bulk actions, WPML hooks, and Polylang hooks.
- Drupal connector with standalone preview route and optional TMGMT translator provider.
- Starter Django connector.

Recommended next upgrades:

- Admin UI for provider key management.
- Encrypted admin UI for internal NLLB/provider settings.
- Multi-target text translation UI.
- `.csv` translation support.
- PDF translation with layout-aware output.
- Encrypted provider key storage in database or secret manager integration.
- Per-integration provider allowlist.
- Per-integration model allowlist.
- Per-integration monthly token/request limits.
- Webhook signing.
- Async background workers for large batch jobs.
- Marketplace-ready WordPress plugin packaging.
- Deeper WordPress custom-field/page-builder translation mapping.
- Drupal TMGMT continuous-job tuning and queue batching for very large sites.
- Django package with installable `pyproject.toml`.
- Production migrations with Alembic.
"# Translator-App" 
