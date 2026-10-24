# Business Analytics Chatbot

Local-first business analytics chatbot with a FastAPI backend and React/Vite frontend. Upload a CSV or Excel dataset, ask questions in plain language, and receive validated tables or interactive Apache ECharts visualizations.

## Requirements

- Windows, macOS, or Linux
- Python 3.11 or newer
- Node.js 18 or newer and npm
- A Groq API key for natural-language analysis

## Quick start on a new machine

From the cloned repository:

```powershell
cd main_chatbot
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

Copy-Item backend\.env.example backend\.env
Copy-Item frontend\.env.example frontend\.env.local
npm.cmd install --prefix frontend
```

Open `backend\.env`, add the real `GROQ_API_KEY`, and keep that file private. Do not put the key in the frontend or commit either `.env` file.

## Run locally

Open two PowerShell windows. In the first:

```powershell
cd main_chatbot
.\.venv\Scripts\Activate.ps1
python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

In the second:

```powershell
cd main_chatbot
npm.cmd --prefix frontend run dev
```

Open `http://127.0.0.1:5173`. The API and interactive OpenAPI docs are available at `http://127.0.0.1:8000/docs`.

## Verify the installation

```powershell
cd main_chatbot
.\.venv\Scripts\Activate.ps1
python -m pytest backend/tests -q
npm.cmd --prefix frontend run build
```

## Project structure

```text
main_chatbot/
├── backend/          FastAPI API, session handling, chart analysis, tests
├── frontend/         React/Vite user interface and Apache ECharts rendering
├── requirements.txt  Python dependencies
└── README.md         Setup and operating instructions
```

## Security and production note

Uploaded files and generated charts are kept in the local backend session storage. The current session store is in-memory and is suitable for a single-process internal deployment. Before a multi-worker production deployment, replace it with Redis or a database, add authentication/authorization, use HTTPS, configure a trusted CORS allowlist, and store secrets in the deployment platform's secret manager.
