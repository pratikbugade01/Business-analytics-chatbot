# Business Analytics Chatbot Backend

The backend is a FastAPI service. Run commands from the `main_chatbot` directory so the `backend` package and its relative imports resolve consistently.

## Setup

```powershell
cd main_chatbot
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item backend\.env.example backend\.env
```

Set `GROQ_API_KEY` in `backend\.env`. This is a server-only secret; never put it in the frontend or in a variable beginning with `VITE_`.

## Run

```powershell
cd main_chatbot
.\.venv\Scripts\Activate.ps1
python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

The API is available at `http://127.0.0.1:8000`; interactive documentation is at `http://127.0.0.1:8000/docs`.

## API flow

1. `POST /datasets` with a CSV or Excel file.
2. Read the returned `session_id`.
3. `POST /sessions/{session_id}/chat` with `{ "question": "..." }`.
4. Render the returned chart data when the response type is `chart`.
5. `DELETE /sessions/{session_id}` when finished.

## Tests

```powershell
cd main_chatbot
.\.venv\Scripts\Activate.ps1
python -m pytest backend/tests -q
```

The session store is intentionally in-memory. Use Redis or a database, plus authentication and HTTPS, before running multiple production workers.

