# Business Analytics Chatbot Frontend

React/Vite frontend for the FastAPI business analytics chatbot. Apache ECharts renders charts in the browser, so chart responses remain interactive rather than becoming static PNG/JPG files.

## Setup

From the repository root:

```powershell
cd main_chatbot
npm.cmd install --prefix frontend
Copy-Item frontend\.env.example frontend\.env.local
```

The default API address is:

```text
VITE_API_BASE_URL=http://127.0.0.1:8000
```

## Run

Start the backend first, then start Vite in another terminal:

```powershell
cd main_chatbot
npm.cmd --prefix frontend run dev
```

Open `http://127.0.0.1:5173` in your browser.

## Production build

```powershell
cd main_chatbot
npm.cmd --prefix frontend run build
```

The generated `frontend/dist` directory is ignored by Git and can be served by a static host or reverse proxy configured to reach the backend API.

