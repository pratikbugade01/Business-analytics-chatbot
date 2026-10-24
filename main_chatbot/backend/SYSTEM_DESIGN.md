# Production system design

## Runtime boundaries

```text
React/Vite + Apache ECharts
          |
          | HTTPS / JSON / multipart upload
          v
FastAPI API
  |-- request validation, CORS, request IDs, error mapping
  |-- dataset/session application service
  |-- deterministic chart specification service
  |-- PandasAI fallback analysis service
          |
          |-- object storage for uploaded datasets and exports
          |-- Redis for session metadata and short-lived locks
          |-- managed database for audit metadata and access control
          |-- LLM provider through server-only credentials
```

## Current safe baseline

The current application keeps the active DataFrame and PandasAI agent in a
thread-safe in-memory store for local development. This is safe for one local
process, but it is not sufficient for multiple production workers or automatic
restarts. The next deployment step must replace `SessionStore` with Redis (or a
database-backed repository) and move uploads from the local filesystem to
private object storage.

## Production rules

- Never send `GROQ_API_KEY` to the browser or use a `VITE_` prefix for secrets.
- Keep chart generation deterministic when the question names a measure,
  dimension, date range, or limit; return a validation error when a requested
  field cannot be identified.
- Store only dataset metadata in logs. Never log uploaded rows, prompts that
  contain sensitive data, or model secrets.
- Enforce upload size, extension, content validation, retention, and deletion.
- Use HTTPS, an explicit CORS allow-list, authentication, authorization, and
  audit logging before finance-department use.
- Add regression tests for every chart type and every supported filter before
  changing aggregation logic.

## Target backend layout

```text
main_chatbot/backend/
  api/              # route handlers and HTTP-only concerns
  core/             # settings, logging, security, lifecycle
  domain/           # dataset/session contracts and business rules
  services/         # analytics, chart specs, PandasAI orchestration
  repositories/     # Redis/database/object-storage adapters
  schemas/          # request/response DTOs
  tests/            # API, analytics, security, and dataset fixtures
  main.py           # application composition only
```
