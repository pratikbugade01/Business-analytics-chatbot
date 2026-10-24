import { StrictMode, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import ReactECharts from "echarts-for-react";
import "./styles.css";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

const suggestions = [
  "What is this dataset about?",
  "Show the top 10 categories by total revenue in a table.",
  "Create a line chart showing the daily trend for the most important series.",
];

function App() {
  const [session, setSession] = useState(null);
  const [dashboard, setDashboard] = useState(null);
  const [messages, setMessages] = useState([]);
  const [question, setQuestion] = useState("");
  const [selectedFile, setSelectedFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [asking, setAsking] = useState(false);
  const [apiOnline, setApiOnline] = useState(null);
  const messagesEnd = useRef(null);

  useEffect(() => {
    fetch(`${API_BASE}/health`)
      .then((response) => setApiOnline(response.ok))
      .catch(() => setApiOnline(false));
  }, []);

  useEffect(() => {
    messagesEnd.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, asking]);

  async function uploadDataset() {
    if (!selectedFile || uploading) return;
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", selectedFile);
      const response = await fetch(`${API_BASE}/datasets`, { method: "POST", body: formData });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Dataset upload failed.");
      setSession(payload);
      setDashboard(null);
      setMessages([{ role: "assistant", content: `Dataset ready. I found ${payload.rows.toLocaleString()} rows and ${payload.columns.length} columns.` }]);
    } catch (error) {
      setMessages((current) => [...current, { role: "assistant", error: error.message }]);
    } finally {
      setUploading(false);
    }
  }

  async function loadDashboard() {
    if (!session) return;
    setDashboard({ loading: true });
    try {
      const response = await fetch(`${API_BASE}/sessions/${session.session_id}/dashboard`);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Dashboard generation failed.");
      setDashboard(payload);
    } catch (error) {
      setDashboard({ error: error.message });
    }
  }

  async function deleteDataset() {
    if (!session || deleting) return;
    if (!window.confirm(`Delete "${session.filename}" and its session data?`)) return;
    setDeleting(true);
    try {
      const response = await fetch(`${API_BASE}/sessions/${session.session_id}`, { method: "DELETE" });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || "Dataset deletion failed.");
      setSession(null);
      setDashboard(null);
      setMessages([]);
      setQuestion("");
      setSelectedFile(null);
      const fileInput = document.getElementById("dataset-file");
      if (fileInput) fileInput.value = "";
    } catch (error) {
      setMessages((current) => [...current, { role: "assistant", error: error.message }]);
    } finally {
      setDeleting(false);
    }
  }

  async function askQuestion(event) {
    event?.preventDefault();
    const trimmed = question.trim();
    if (!session || !trimmed || asking) return;
    setMessages((current) => [...current, { role: "user", content: trimmed }]);
    setQuestion("");
    setAsking(true);
    try {
      const response = await fetch(`${API_BASE}/sessions/${session.session_id}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: trimmed }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "The analysis request failed.");
      setMessages((current) => [...current, { role: "assistant", response: payload }]);
    } catch (error) {
      setMessages((current) => [...current, { role: "assistant", error: error.message }]);
    } finally {
      setAsking(false);
    }
  }

  function clearConversation() {
    setMessages(session ? [{ role: "assistant", content: "Conversation cleared. Ask a new question about your active dataset." }] : []);
  }

  function handleQuestionKeyDown(event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      askQuestion(event);
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">PANDASAI WORKSPACE</p>
          <h1>Business analytics chatbot</h1>
          <p className="subtitle">Upload a dataset, ask a question, and turn your numbers into decisions.</p>
        </div>
        <div className={`status-pill ${apiOnline === true ? "online" : apiOnline === false ? "error" : ""}`}>
          {apiOnline === true ? "API connected" : apiOnline === false ? "API offline" : "Checking API…"}
        </div>
      </header>

      <section className="workspace-grid">
        <aside className="panel dataset-panel">
          <div className="panel-heading"><div><p className="eyebrow">DATASET</p><h2>Start a session</h2></div><span className="step-number">01</span></div>
          <label className="upload-dropzone" htmlFor="dataset-file">
            <input id="dataset-file" type="file" accept=".csv,.xls,.xlsx" onChange={(event) => setSelectedFile(event.target.files?.[0] || null)} />
            <span className="upload-icon">↥</span>
            <strong>{selectedFile ? selectedFile.name : "Choose CSV or Excel"}</strong>
            <span>Maximum 25 MB</span>
          </label>
          <button className="primary-button" type="button" onClick={uploadDataset} disabled={!selectedFile || uploading}>{uploading ? "Uploading…" : "Upload dataset"}</button>

          {session && <><div className="dataset-summary"><div className="summary-label">ACTIVE DATASET</div><strong>{session.filename}</strong><span>{session.rows.toLocaleString()} rows · {session.columns.length} columns</span><code>{session.session_id}</code></div><button className="dashboard-button" type="button" onClick={loadDashboard} disabled={dashboard?.loading}>{dashboard?.loading ? "Building dashboard…" : "Build executive dashboard"}</button></>}

          {session && <button className="delete-dataset-button" type="button" onClick={deleteDataset} disabled={deleting}>{deleting ? "Deleting…" : "Delete active dataset"}</button>}
          <div className="prompt-library"><div className="summary-label">TRY A QUESTION</div>{suggestions.map((prompt) => <button className="suggestion" type="button" key={prompt} onClick={() => setQuestion(prompt)}>{prompt}</button>)}</div>
        </aside>

        <section className="panel chat-panel">
          <div className="panel-heading"><div><p className="eyebrow">ANALYSIS</p><h2>Ask your data</h2></div><button className="ghost-button" type="button" onClick={clearConversation}>Clear</button></div>
          {dashboard && <Dashboard dashboard={dashboard} />}
          <div className="messages" aria-live="polite">
            {!messages.length && <div className="empty-state"><div className="empty-mark">✦</div><h3>Your dataset is waiting</h3><p>Upload a CSV or Excel file, then ask for an insight, table, or chart.</p></div>}
            {messages.map((message, index) => <Message key={`${message.role}-${index}`} message={message} />)}
            {asking && <div className="typing"><span></span><span></span><span></span> Analyzing your dataset…</div>}
            <div ref={messagesEnd} />
          </div>
          <form className="composer" onSubmit={askQuestion}><textarea value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={handleQuestionKeyDown} disabled={!session || asking} maxLength={4000} rows="2" placeholder={session ? "Ask about your data…" : "Upload a dataset to start…"} aria-label="Ask about your data" /><button className="send-button" type="submit" disabled={!session || !question.trim() || asking} aria-label="Send question">↑</button></form>
          <p className="privacy-note">Your file stays in this local backend session. Do not upload sensitive data to an untrusted server.</p>
        </section>
      </section>
    </main>
  );
}

function Message({ message }) {
  return <article className={`message ${message.role}`}><div className="message-badge">{message.role === "user" ? "YOU" : "AI"}</div><div className={`bubble ${message.error ? "error-bubble" : ""}`}>{message.error ? message.error : message.response ? <ResponseView response={message.response} /> : message.content}</div></article>;
}

function ResponseView({ response }) {
  if (response.type === "chart_spec") return <InteractiveChart spec={response.value} />;
  if (response.type === "chart") return <div className="error-bubble">Static chart responses are disabled. Please retry to generate an interactive Apache ECharts chart.</div>;
  if (response.type === "dataframe") return <DataTable rows={response.value} />;
  if (response.value && typeof response.value === "object") return <pre>{JSON.stringify(response.value, null, 2)}</pre>;
  return <span>{response.value ?? response.message ?? "No response returned."}</span>;
}

function InteractiveChart({ spec }) {
  const option = buildEChartOption(spec);
  return <ChartViewer title={spec.title} option={option} format={spec.format} kind={spec.kind} className="interactive-chart" />;
}

function ChartViewer({ title, option, format, kind, className = "chart-panel" }) {
  const [maximized, setMaximized] = useState(false);
  const [selectedDetail, setSelectedDetail] = useState(null);

  useEffect(() => {
    if (!maximized) return undefined;
    const onKeyDown = (event) => event.key === "Escape" && setMaximized(false);
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [maximized]);

  function handleChartClick(params) {
    if (!params) return;
    const rawValue = Array.isArray(params.value) ? params.value : [params.value];
    const label = params.axisValueLabel || params.axisValue || params.name || "Selected point";
    if (kind === "candlestick" && rawValue.length >= 4) {
      setSelectedDetail({ label, entries: [["Open", rawValue[0]], ["Close", rawValue[1]], ["Low", rawValue[2]], ["High", rawValue[3]]] });
      return;
    }
    if (kind === "pie") {
      setSelectedDetail({ label, entries: [["Amount", rawValue[0]], ["Share", params.percent || 0, "percent"]] });
      return;
    }
    if (kind === "box" && rawValue.length >= 5) {
      setSelectedDetail({ label, entries: [["Min", rawValue[0]], ["Q1", rawValue[1]], ["Median", rawValue[2]], ["Q3", rawValue[3]], ["Max", rawValue[4]]] });
      return;
    }
    if (kind === "scatter" && rawValue.length >= 2) {
      setSelectedDetail({ label, entries: [["X", rawValue[0]], ["Y", rawValue[1]]] });
      return;
    }
    if (kind === "heatmap" && rawValue.length >= 3) {
      setSelectedDetail({ label, entries: [["Correlation", rawValue[2]]] });
      return;
    }
    setSelectedDetail({ label, entries: [[params.seriesName || "Value", rawValue[0]]] });
  }

  const chartEvents = { click: handleChartClick };

  return <>
    <article className={className} role="group" aria-label={`${title} interactive chart`}>
      <div className="chart-panel-heading">
        <div><h4>{title}</h4><span>Apache ECharts · {format || "Analysis"}</span></div>
        <div className="chart-actions">
          <button type="button" className="chart-action primary icon-button" aria-label="Maximize chart" title="Maximize chart" onClick={() => setMaximized(true)}><MaximizeIcon /></button>
        </div>
      </div>
      <ReactECharts option={option} notMerge lazyUpdate onEvents={chartEvents} style={{ width: "100%", height: 320 }} opts={{ renderer: "canvas" }} />
      {selectedDetail && <TapDetail detail={selectedDetail} format={format} onClear={() => setSelectedDetail(null)} />}
    </article>
    {maximized && <div className="chart-modal-backdrop" role="dialog" aria-modal="true" aria-label={`${title} maximized`} onMouseDown={(event) => event.target === event.currentTarget && setMaximized(false)}>
      <section className="chart-modal">
        <div className="chart-modal-heading"><div><p className="eyebrow">MAXIMIZED CHART</p><h3>{title}</h3></div><div className="chart-actions"><button type="button" className="chart-action primary icon-button" aria-label="Close maximized chart" title="Close" onClick={() => setMaximized(false)}><CloseIcon /></button></div></div>
        <ReactECharts option={option} notMerge lazyUpdate onEvents={chartEvents} style={{ width: "100%", height: "calc(100vh - 170px)" }} opts={{ renderer: "canvas" }} />
      </section>
    </div>}
  </>;
}

function TapDetail({ detail, format, onClear }) {
  return <div className="tap-detail"><div><span className="tap-detail-label">SELECTED · {detail.label}</span><div className="tap-detail-values">{detail.entries.map(([label, value, entryFormat]) => <span key={label}><small>{label}</small><strong>{formatMetric(value, entryFormat || format)}</strong></span>)}</div></div><button type="button" className="tap-detail-close" aria-label="Clear selected chart detail" title="Clear selected detail" onClick={onClear}>×</button></div>;
}

function MaximizeIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 3H3v5M3 3l7 7M16 3h5v5M21 3l-7 7M8 21H3v-5M3 21l7-7M16 21h5v-5M21 21l-7-7" /></svg>;
}

function CloseIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18" /></svg>;
}

function boxSummary(values) {
  const numbers = values.map(Number).filter(Number.isFinite).sort((a, b) => a - b);
  if (!numbers.length) return [0, 0, 0, 0, 0];
  const percentile = (fraction) => numbers[Math.min(numbers.length - 1, Math.floor((numbers.length - 1) * fraction))];
  return [numbers[0], percentile(0.25), percentile(0.5), percentile(0.75), numbers[numbers.length - 1]];
}

function buildEChartOption(spec) {
  const valueFormatter = (value) => formatMetric(value, spec.format);
  const pointCount = spec.data?.length || 0;
  const common = { backgroundColor: "transparent", animation: true, animationThreshold: 2000, aria: { enabled: true, decal: { show: false } }, toolbox: { right: 6, feature: { dataView: { readOnly: true, title: "View data" }, restore: { title: "Reset" }, saveAsImage: { title: "Download PNG", type: "png", pixelRatio: 3 } } }, tooltip: { trigger: "axis", confine: true, axisPointer: { type: "cross", label: { backgroundColor: "#526274" } }, backgroundColor: "#18232e", borderColor: "#9ff4c7", textStyle: { color: "#fff" }, valueFormatter } };
  if (spec.kind === "pie" || spec.kind === "donut") return { ...common, tooltip: { ...common.tooltip, trigger: "item", formatter: ({ name, value, percent }) => `${name}<br/>${valueFormatter(value)} · ${Number(percent).toFixed(1)}%` }, legend: { type: "scroll", orient: "vertical", left: 8, top: 12, bottom: 12, textStyle: { color: "#95a2b3", fontSize: 11 } }, series: [{ type: "pie", name: spec.title, radius: spec.kind === "donut" ? ["48%", "72%"] : ["34%", "70%"], center: ["62%", "52%"], avoidLabelOverlap: true, itemStyle: { borderColor: "#151b24", borderWidth: 2, borderRadius: 4 }, label: { color: "#d8e2ee", formatter: "{b}\n{d}%" }, emphasis: { label: { show: true, fontSize: 14, fontWeight: "bold" } }, data: spec.data, progressive: 500, progressiveThreshold: 1000 }] };
  if (spec.kind === "scatter") return { ...common, grid: { left: 66, right: 24, top: 34, bottom: 52 }, xAxis: { type: "value", name: spec.x_axis, nameTextStyle: { color: "#95a2b3" }, axisLabel: { color: "#95a2b3", formatter: valueFormatter }, splitLine: { lineStyle: { color: "#2a3543", type: "dashed" } } }, yAxis: { type: "value", name: spec.y_axis, nameTextStyle: { color: "#95a2b3" }, axisLabel: { color: "#95a2b3", formatter: valueFormatter }, splitLine: { lineStyle: { color: "#2a3543", type: "dashed" } } }, series: [{ type: "scatter", data: spec.data.map((item) => [item.x, item.y]), symbolSize: 10, itemStyle: { color: "#9ff4c7", shadowBlur: 8, shadowColor: "#9ff4c766" }, progressive: 1000, progressiveThreshold: 2000, large: spec.data.length > 3000, largeThreshold: 3000 }] };
  if (spec.kind === "histogram") return { ...common, grid: { left: 62, right: 24, top: 34, bottom: 72 }, xAxis: { type: "category", data: spec.data.map((item) => item.category), axisLabel: { color: "#95a2b3", rotate: 35 } }, yAxis: { type: "value", name: spec.y_axis, axisLabel: { color: "#95a2b3", formatter: valueFormatter }, splitLine: { lineStyle: { color: "#2a3543", type: "dashed" } } }, series: [{ type: "bar", data: spec.data.map((item) => item.value), itemStyle: { color: "#75a8ff", borderRadius: [5, 5, 0, 0] }, label: { show: spec.data.length < 30, position: "top", color: "#d8e2ee" } }] };
  if (spec.kind === "box") return { ...common, tooltip: { ...common.tooltip, trigger: "item" }, grid: { left: 62, right: 24, top: 34, bottom: 52 }, xAxis: { type: "category", data: spec.data.map((item) => item.name), axisLabel: { color: "#95a2b3", rotate: 25 } }, yAxis: { type: "value", axisLabel: { color: "#95a2b3", formatter: valueFormatter }, splitLine: { lineStyle: { color: "#2a3543", type: "dashed" } } }, series: [{ type: "boxplot", data: spec.data.map((item) => boxSummary(item.value)), itemStyle: { color: "#9ff4c7", borderColor: "#9ff4c7" } }] };
  if (spec.kind === "heatmap") return { ...common, tooltip: { ...common.tooltip, trigger: "item", formatter: ({ value }) => `${spec.x_labels[value[0]]} × ${spec.y_labels[value[1]]}<br/>${Number(value[2]).toFixed(3)}` }, grid: { left: 100, right: 30, top: 24, bottom: 80 }, xAxis: { type: "category", data: spec.x_labels, axisLabel: { color: "#95a2b3", rotate: 35 } }, yAxis: { type: "category", data: spec.y_labels, axisLabel: { color: "#95a2b3" } }, visualMap: { min: -1, max: 1, calculable: true, orient: "horizontal", left: "center", bottom: 8, textStyle: { color: "#95a2b3" } }, series: [{ type: "heatmap", data: spec.data.map((item) => [item.x, item.y, item.value]), label: { show: spec.data.length < 100, color: "#fff" }, progressive: 1000, progressiveThreshold: 2000 }] };
  if (spec.kind === "candlestick") return { ...common, dataZoom: [{ type: "inside", xAxisIndex: 0 }, { type: "slider", xAxisIndex: 0, height: 18, bottom: 4 }], grid: { left: 62, right: 24, top: 34, bottom: 72 }, xAxis: { type: "category", data: spec.data.map((item) => item.date), axisLabel: { color: "#95a2b3", rotate: 35 }, axisLine: { lineStyle: { color: "#526274" } } }, yAxis: { scale: true, axisLabel: { color: "#95a2b3", formatter: valueFormatter }, splitLine: { lineStyle: { color: "#2a3543", type: "dashed" } } }, series: [{ type: "candlestick", name: spec.title, data: spec.data.map((item) => [item.open, item.close, item.low, item.high]), itemStyle: { color: "#9ff4c7", color0: "#ef8f9b", borderColor: "#9ff4c7", borderColor0: "#ef8f9b" }, progressive: 500, progressiveThreshold: 1000, large: pointCount > 3000, largeThreshold: 3000 }] };
  if (spec.kind === "bar") return { ...common, dataZoom: [{ type: "inside", yAxisIndex: 0 }, { type: "slider", yAxisIndex: 0, width: 18, right: 2 }], grid: { left: 130, right: 40, top: 34, bottom: 42 }, xAxis: { type: "value", axisLabel: { color: "#95a2b3", formatter: valueFormatter }, splitLine: { lineStyle: { color: "#2a3543", type: "dashed" } } }, yAxis: { type: "category", data: spec.data.map((item) => item.category), axisLabel: { color: "#95a2b3" } }, series: [{ type: "bar", data: spec.data.map((item) => item.value), itemStyle: { color: "#9ff4c7", borderRadius: [0, 5, 5, 0] }, label: { show: pointCount < 40, position: "right", color: "#d8e2ee", formatter: ({ value }) => valueFormatter(value) }, progressive: 500, progressiveThreshold: 1000, large: pointCount > 3000, largeThreshold: 3000 }] };
  if (spec.series_key) {
    const seriesNames = [...new Set(spec.data.map((item) => item[spec.series_key]))];
    const categories = [...new Set(spec.data.map((item) => item[spec.x_axis]))];
    const colors = ["#9ff4c7", "#75a8ff", "#f2c777", "#ef8f9b", "#c49cff", "#64d6d2"];
    return { ...common, legend: { type: "scroll", top: 8, textStyle: { color: "#95a2b3" }, data: seriesNames, selectedMode: "multiple" }, grid: { left: 66, right: 24, top: 46, bottom: 72 }, xAxis: { type: "category", data: categories, axisLabel: { color: "#95a2b3", rotate: 35 } }, yAxis: { type: "value", name: spec.y_axis, axisLabel: { color: "#95a2b3", formatter: valueFormatter }, splitLine: { lineStyle: { color: "#2a3543", type: "dashed" } } }, series: seriesNames.map((name, index) => ({ type: "line", name, data: categories.map((category) => { const point = spec.data.find((item) => item[spec.series_key] === name && item[spec.x_axis] === category); return point?.value ?? null; }), connectNulls: false, smooth: true, showSymbol: categories.length < 1000, lineStyle: { color: colors[index % colors.length], width: 2 }, itemStyle: { color: colors[index % colors.length] }, areaStyle: spec.kind === "area" ? { opacity: 0.12 } : undefined })) };
  }
  return { ...common, dataZoom: [{ type: "inside", xAxisIndex: 0 }, { type: "slider", xAxisIndex: 0, height: 18, bottom: 4 }], grid: { left: 62, right: 24, top: 34, bottom: 72 }, xAxis: { type: "category", data: spec.data.map((item) => item[spec.x_axis]), axisLabel: { color: "#95a2b3", rotate: 35 }, axisLine: { lineStyle: { color: "#526274" } } }, yAxis: { type: "value", axisLabel: { color: "#95a2b3", formatter: valueFormatter }, splitLine: { lineStyle: { color: "#2a3543", type: "dashed" } } }, series: [{ type: "line", name: spec.title, data: spec.data.map((item) => item.value), smooth: true, showSymbol: pointCount < 1000, sampling: pointCount > 1000 ? "lttb" : undefined, progressive: 500, progressiveThreshold: 1000, large: pointCount > 3000, largeThreshold: 3000, lineStyle: { color: "#9ff4c7", width: 3 }, areaStyle: { color: "rgba(159,244,199,.12)" } }] };
}

function DataTable({ rows }) {
  if (!Array.isArray(rows) || !rows.length) return <span>No rows returned.</span>;
  const columns = Object.keys(rows[0]);
  return <div className="result-table"><table><thead><tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{columns.map((column) => <td key={column}>{String(row[column] ?? "—")}</td>)}</tr>)}</tbody></table></div>;
}

function formatMetric(value, format) {
  if (value === null || value === undefined) return "—";
  if (format === "INR") return `₹${Number(value).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
  if (format === "percent") return `${Number(value).toFixed(1)}%`;
  return Number(value).toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

function Dashboard({ dashboard }) {
  if (dashboard.loading) return <div className="dashboard-loading">Building a business dashboard from your data…</div>;
  if (dashboard.error) return <div className="dashboard-error">{dashboard.error}</div>;
  return <section className="dashboard"><div className="dashboard-title"><div><p className="eyebrow">EXECUTIVE VIEW</p><h3>{dashboard.title}</h3><p>{dashboard.subtitle}</p></div><span className="profile-badge">{dashboard.profile?.rows?.toLocaleString()} rows analyzed</span></div>{dashboard.profile && <div className="dashboard-facts"><span><b>Measure</b> {dashboard.profile.primary_measure || "Detected automatically"}</span><span><b>Date</b> {dashboard.profile.date_column || "Not detected"}</span><span><b>Dimensions</b> {dashboard.profile.category_columns?.slice(0, 4).join(", ") || "None"}</span><span><b>Missing</b> {dashboard.profile.missing_values ?? 0} values</span></div>}<div className="kpi-grid">{dashboard.kpis.map((kpi) => <div className="kpi-card" key={kpi.label}><span>{kpi.label}</span><strong className={kpi.trend === "down" ? "negative" : ""}>{formatMetric(kpi.value, kpi.format)}</strong></div>)}</div><div className="dashboard-charts">{dashboard.charts.map((chart) => <ChartCard chart={chart} key={chart.id} />)}</div><div className="insight-list"><span className="summary-label">KEY TAKEAWAYS</span>{dashboard.insights.map((insight) => <p key={insight}>↗ {insight}</p>)}</div></section>;
}

function ChartCard({ chart }) {
  const isLine = chart.kind === "line";
  const isPie = chart.kind === "pie" || chart.kind === "donut";
  const series = isLine ? [...new Set(chart.data.map((row) => row[chart.series_key]))] : [];
  const data = isLine ? chart.data.reduce((result, row) => { const existing = result.find((item) => item[chart.x_key] === row[chart.x_key]); if (existing) existing[row[chart.series_key]] = row[chart.y_key]; else result.push({ [chart.x_key]: row[chart.x_key], [row[chart.series_key]]: row[chart.y_key] }); return result; }, []) : chart.data;
  const option = isPie ? buildEChartOption({ kind: chart.kind, title: chart.title, format: chart.format, data: chart.data }) : isLine ? { ...buildEChartOption({ kind: "line", title: chart.title, format: chart.format, x_axis: chart.x_key, data: data.flatMap((row) => series.map((name) => ({ [chart.x_key]: row[chart.x_key], value: row[name], series: name }))) }), legend: { show: true, textStyle: { color: "#95a2b3" }, data: series, selectedMode: "multiple" }, series: series.map((name, index) => ({ type: "line", name, data: data.map((row) => row[name]), smooth: true, showSymbol: data.length < 1000, sampling: data.length > 1000 ? "lttb" : undefined, progressive: 500, progressiveThreshold: 1000, large: data.length > 3000, largeThreshold: 3000, lineStyle: { color: ["#9ff4c7", "#75a8ff", "#f2c777", "#ef8f9b", "#c49cff", "#64d6d2"][index % 6], width: 2 } })) } : buildEChartOption({ kind: chart.kind || "bar", title: chart.title, format: chart.format, data: chart.data.map((row) => ({ category: row[chart.x_key], value: row[chart.y_key] })) });
  return <ChartViewer title={chart.title} option={option} format={chart.format === "INR" ? "INR" : "Analysis"} kind={chart.kind} />;
}

createRoot(document.getElementById("root")).render(<StrictMode><App /></StrictMode>);

