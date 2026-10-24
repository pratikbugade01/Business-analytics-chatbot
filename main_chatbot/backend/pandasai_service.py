from __future__ import annotations

import base64
import io
import logging
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
import pandasai as pai
from pandasai.agent import Agent
from pandasai_litellm.litellm import LiteLLM

from .config import Settings
from .schemas import ChatResponse, DatasetResponse
from .session_store import ChatSession, SessionStore, utc_now

logger = logging.getLogger(__name__)


class PandasAIService:
    """Application boundary around PandasAI and the configured LLM."""

    ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls"}

    def __init__(self, settings: Settings, sessions: SessionStore) -> None:
        self.settings = settings
        self.sessions = sessions
        self.settings.create_runtime_directories()

        self.llm = LiteLLM(
            model=settings.llm_model,
            api_key=settings.groq_api_key,
            max_tokens=settings.llm_max_tokens,
            temperature=settings.llm_temperature,
        )
        pai.config.set(
            {
                "llm": self.llm,
                "max_retries": settings.pandasai_max_retries,
                "verbose": False,
            }
        )

    def create_dataset(self, filename: str, content: bytes) -> DatasetResponse:
        extension = Path(filename).suffix.lower()
        if extension not in self.ALLOWED_EXTENSIONS:
            raise ValueError("Only CSV, XLS, and XLSX files are supported.")
        if not content:
            raise ValueError("The uploaded file is empty.")
        if len(content) > self.settings.max_upload_size_bytes:
            raise ValueError(
                f"The file exceeds the {self.settings.max_upload_size_mb} MB limit."
            )

        session_id = str(uuid.uuid4())
        safe_name = f"{session_id}{extension}"
        upload_path = self.settings.upload_directory / safe_name
        upload_path.write_bytes(content)

        try:
            dataframe = self._load_dataframe(upload_path, extension)
            self._validate_dataframe(dataframe)
            pai_dataframe = pai.DataFrame(dataframe)
            agent = Agent([pai_dataframe])
        except Exception:
            upload_path.unlink(missing_ok=True)
            raise

        try:
            self.sessions.create(
                ChatSession(
                    session_id=session_id,
                    filename=Path(filename).name,
                    dataframe=pai_dataframe,
                    source_dataframe=dataframe,
                    agent=agent,
                    upload_path=str(upload_path),
                )
            )
        except Exception:
            upload_path.unlink(missing_ok=True)
            raise
        return DatasetResponse(
            session_id=session_id,
            filename=Path(filename).name,
            rows=len(dataframe),
            columns=[str(column) for column in dataframe.columns],
            created_at=utc_now(),
        )

    def build_dashboard(self, session_id: str) -> dict[str, Any]:
        """Build deterministic KPI and chart data for the Power BI-style view."""
        session = self.sessions.get(session_id)
        if session is None:
            raise KeyError("Dataset session was not found.")

        frame = session.source_dataframe.copy()
        date_columns = [column for column in frame.columns if self._parse_date(column)]
        if "Particulars" in frame.columns and len(date_columns) >= 3:
            return self._build_wide_financial_dashboard(session_id, frame, date_columns)
        return self._build_tabular_dashboard(session_id, frame)

    @staticmethod
    def _parse_date(value: Any) -> pd.Timestamp | None:
        parsed = pd.to_datetime(str(value), format="%d/%m/%Y", errors="coerce")
        return parsed if not pd.isna(parsed) else None

    @staticmethod
    def _number(value: Any) -> int | float | None:
        if pd.isna(value):
            return None
        value = value.item() if hasattr(value, "item") else value
        return round(float(value), 2) if isinstance(value, float) else value

    @classmethod
    def _clean_rows(cls, frame: pd.DataFrame) -> pd.DataFrame:
        result = frame.dropna(how="all").copy()
        if "Particulars" in result.columns:
            names = result["Particulars"].astype(str).str.strip()
            result = result[(names != "") & (~names.str.lower().str.startswith("total"))]
        return result

    def _build_wide_financial_dashboard(self, session_id: str, frame: pd.DataFrame, date_columns: list[Any]) -> dict[str, Any]:
        clean = self._clean_rows(frame)
        ordered_dates = sorted(date_columns, key=lambda column: self._parse_date(column))
        long = clean.melt(id_vars=["Particulars"], value_vars=ordered_dates, var_name="date", value_name="value")
        long["date"] = long["date"].map(self._parse_date)
        long["value"] = pd.to_numeric(long["value"], errors="coerce")
        long = long.dropna(subset=["date", "value"])

        daily = long.groupby("date", as_index=False)["value"].sum().sort_values("date")
        category_means = long.groupby("Particulars", as_index=False)["value"].mean().sort_values("value", ascending=False)
        top_categories = category_means.head(6)["Particulars"].tolist()
        trend = long[long["Particulars"].isin(top_categories)].copy()
        trend["date"] = trend["date"].dt.strftime("%Y-%m-%d")
        trend_rows = [{"date": row.date, "category": row.Particulars, "value": self._number(row.value)} for row in trend.itertuples(index=False)]
        category_rows = [{"category": row.Particulars, "value": self._number(row.value)} for row in category_means.head(10).itertuples(index=False)]

        latest_date = daily.iloc[-1]["date"]
        latest_distribution = long[long["date"] == latest_date].groupby("Particulars", as_index=False)["value"].sum().sort_values("value", ascending=False)
        latest_top = latest_distribution.head(10).copy()
        if len(latest_distribution) > len(latest_top):
            latest_top = pd.concat([latest_top, pd.DataFrame([{"Particulars": "Other", "value": latest_distribution.iloc[len(latest_top):]["value"].sum()}])], ignore_index=True)
        distribution_rows = [{"name": str(row.Particulars), "value": self._number(row.value)} for row in latest_top.itertuples(index=False)]

        account_daily = long.pivot_table(index="date", columns="Particulars", values="value", aggfunc="sum")
        period_rows = []
        volatility_rows = []
        for name in category_means.head(10)["Particulars"].tolist():
            values = account_daily[name].dropna() if name in account_daily.columns else pd.Series(dtype=float)
            if values.empty:
                continue
            period_rows.append({"category": str(name), "value": self._number(float(values.iloc[-1] - values.iloc[0]))})
            changes = values.pct_change().replace([float("inf"), -float("inf")], pd.NA).dropna()
            volatility_rows.append({"category": str(name), "value": self._number(float(changes.std() * 100) if not changes.empty else 0)})
        total_rows = [{"date": row.date.strftime("%Y-%m-%d"), "category": "Total daily value", "value": self._number(row.value)} for row in daily.itertuples(index=False)]

        first_value = float(daily.iloc[0]["value"])
        latest_value = float(daily.iloc[-1]["value"])
        change = latest_value - first_value
        change_pct = (change / first_value * 100) if first_value else 0
        daily_changes = daily["value"].pct_change().replace([float("inf"), -float("inf")], pd.NA).dropna()
        volatility = float(daily_changes.std() * 100) if not daily_changes.empty else 0
        direction = "increased" if change >= 0 else "decreased"

        return {
            "type": "dashboard",
            "session_id": session_id,
            "title": "Financial performance overview",
            "subtitle": f"Daily activity from {daily.iloc[0]['date']:%d %b %Y} to {daily.iloc[-1]['date']:%d %b %Y}",
            "kpis": [
                {"label": "Latest total", "value": self._number(latest_value), "format": "INR"},
                {"label": "Period change", "value": self._number(change), "format": "INR", "trend": "up" if change >= 0 else "down"},
                {"label": "Change %", "value": self._number(change_pct), "format": "percent", "trend": "up" if change >= 0 else "down"},
                {"label": "Daily volatility", "value": self._number(volatility), "format": "percent"},
            ],
            "insights": [
                f"The combined daily value {direction} by {abs(change_pct):.1f}% over the period.",
                f"{top_categories[0]} has the highest average daily value among the tracked categories." if top_categories else "No category ranking was available.",
            ],
            "charts": [
                {"id": "trend", "kind": "line", "title": "Top accounts: daily trend", "data": trend_rows, "x_key": "date", "y_key": "value", "series_key": "category", "format": "INR"},
                {"id": "ranking", "kind": "bar", "title": "Average daily value by account", "data": category_rows, "x_key": "category", "y_key": "value", "format": "INR"},
                {"id": "daily-total", "kind": "line", "title": "Total daily value", "data": total_rows, "x_key": "date", "y_key": "value", "series_key": "category", "format": "INR"},
                {"id": "latest-distribution", "kind": "pie", "title": f"Latest value distribution — {latest_date:%d %b %Y}", "data": distribution_rows, "x_key": "category", "y_key": "value", "format": "INR"},
                {"id": "period-change", "kind": "bar", "title": "Period change by account", "data": period_rows, "x_key": "category", "y_key": "value", "format": "INR"},
                {"id": "account-volatility", "kind": "bar", "title": "Daily volatility by account", "data": volatility_rows, "x_key": "category", "y_key": "value", "format": "percent"},
            ],
            "profile": {"rows": len(frame), "columns": len(frame.columns), "date_columns": len(date_columns), "categories": len(category_means)},
        }

    def _build_tabular_dashboard(self, session_id: str, frame: pd.DataFrame) -> dict[str, Any]:
        numeric_columns = frame.select_dtypes(include="number").columns.tolist()
        all_category_columns = frame.select_dtypes(exclude="number").columns.tolist()
        date_column, parsed_dates = self._choose_date_column(frame)
        category_columns = [column for column in all_category_columns if column != date_column and not self._is_identifier_column(column) and not any(token in str(column).lower() for token in ("date", "month", "time"))]
        charts: list[dict[str, Any]] = []
        kpis: list[dict[str, Any]] = []
        insights: list[str] = []

        if not numeric_columns:
            return {"type": "dashboard", "session_id": session_id, "title": "Dataset overview", "subtitle": f"{len(frame):,} rows · {len(frame.columns)} columns", "kpis": [], "insights": ["No numeric measures were detected, so metric-based charts cannot be generated."], "charts": [], "profile": {"rows": len(frame), "columns": len(frame.columns), "date_column": date_column, "numeric_columns": [], "category_columns": category_columns}}

        primary = self._choose_numeric_measure(numeric_columns)
        primary_format = self._value_format(primary)
        metric_frame = frame.copy()
        metric_frame["_metric"] = pd.to_numeric(metric_frame[primary], errors="coerce")
        metric_frame = metric_frame.dropna(subset=["_metric"])
        numeric = metric_frame["_metric"]
        profit_column = next((column for column in numeric_columns if "profit" in str(column).lower()), None)
        quantity_column = next((column for column in numeric_columns if "quantity" in str(column).lower() or "units" in str(column).lower()), None)

        kpis = [
            {"label": f"Total {primary}", "value": self._number(numeric.sum()), "format": primary_format},
            {"label": f"Average {primary}", "value": self._number(numeric.mean()), "format": primary_format},
            {"label": f"Maximum {primary}", "value": self._number(numeric.max()), "format": primary_format},
        ]
        if profit_column:
            profit = pd.to_numeric(frame[profit_column], errors="coerce").dropna()
            kpis.append({"label": f"Total {profit_column}", "value": self._number(profit.sum()), "format": self._value_format(profit_column)})
            insights.append(f"Total {profit_column} is {self._number(profit.sum()):,.2f}.")
        elif quantity_column:
            quantity = pd.to_numeric(frame[quantity_column], errors="coerce").dropna()
            kpis.append({"label": f"Total {quantity_column}", "value": self._number(quantity.sum()), "format": "number"})

        # Row-level dates are handled separately from wide date-column financial sheets.
        if date_column and parsed_dates is not None:
            metric_frame["_date"] = parsed_dates.loc[metric_frame.index]
            period = "day" if metric_frame["_date"].nunique() <= 45 else "month"
            if period == "month":
                metric_frame["_period"] = metric_frame["_date"].dt.to_period("M").astype(str)
            else:
                metric_frame["_period"] = metric_frame["_date"].dt.strftime("%Y-%m-%d")
            trend = metric_frame.groupby("_period", as_index=False)["_metric"].sum().sort_values("_period")
            charts.append({"id": "time-trend", "kind": "line", "title": f"{period.title()} {primary} trend", "data": [{"period": str(row["_period"]), "series": str(primary), "value": self._number(row["_metric"])} for _, row in trend.iterrows()], "x_key": "period", "y_key": "value", "series_key": "series", "format": primary_format})
            insights.append(f"The dataset covers {metric_frame['_date'].min():%d %b %Y} to {metric_frame['_date'].max():%d %b %Y}.")

        if category_columns:
            preferred_dimensions = self._rank_category_dimensions(frame, category_columns)
            for dimension in preferred_dimensions[:4]:
                grouped = metric_frame.groupby(dimension, dropna=False, as_index=False)["_metric"].sum().sort_values("_metric", ascending=False).head(10)
                rows = [{"category": str(row[dimension]), "value": self._number(row["_metric"])} for _, row in grouped.iterrows()]
                if len(rows) > 1:
                    kind = "pie" if dimension == preferred_dimensions[0] and len(rows) <= 8 else "bar"
                    charts.append({"id": f"{dimension}-performance", "kind": kind, "title": f"{primary} by {dimension}", "data": ([{"name": row["category"], "value": row["value"]} for row in rows] if kind == "pie" else rows), "x_key": "category", "y_key": "value", "format": primary_format})

            if profit_column:
                profit_frame = frame.copy()
                profit_frame["_profit"] = pd.to_numeric(profit_frame[profit_column], errors="coerce")
                profit_frame = profit_frame.dropna(subset=["_profit"])
                dimension = preferred_dimensions[0]
                grouped_profit = profit_frame.groupby(dimension, dropna=False, as_index=False)["_profit"].sum().sort_values("_profit", ascending=False).head(10)
                charts.append({"id": "profit-by-dimension", "kind": "bar", "title": f"{profit_column} by {dimension}", "data": [{"category": str(row[dimension]), "value": self._number(row["_profit"])} for _, row in grouped_profit.iterrows()], "x_key": "category", "y_key": "value", "format": self._value_format(profit_column)})

        if not charts:
            charts.append({"id": "distribution", "kind": "histogram", "title": f"Distribution of {primary}", "data": self._histogram_rows(numeric), "x_key": "category", "y_key": "value", "format": "number"})

        if category_columns:
            insights.append(f"The dashboard analyzed {len(category_columns)} categorical dimensions and selected {primary} as the primary business measure.")
        profile = {"rows": len(frame), "columns": len(frame.columns), "date_column": str(date_column) if date_column else None, "primary_measure": str(primary), "numeric_columns": [str(column) for column in numeric_columns], "category_columns": [str(column) for column in category_columns], "missing_values": int(frame.isna().sum().sum())}
        return {"type": "dashboard", "session_id": session_id, "title": "Dataset performance overview", "subtitle": f"{len(frame):,} rows · {len(frame.columns)} columns", "kpis": kpis[:4], "insights": insights or ["The dashboard selected the available numeric measures and categorical dimensions."], "charts": charts, "profile": profile}

    @staticmethod
    def _is_identifier_column(column: Any) -> bool:
        name = str(column).lower()
        return name in {"id", "name"} or name.endswith("_id") or name.endswith("_code")

    @staticmethod
    def _is_temporal_column(column: Any) -> bool:
        name = re.sub(r"[^a-z0-9]+", "_", str(column).lower()).strip("_")
        return name in {"year", "month", "quarter"} or any(token in name for token in ("date", "time", "timestamp"))

    @staticmethod
    def _value_format(column: Any) -> str:
        name = str(column).lower()
        return "INR" if any(token in name for token in ("inr", "revenue", "sales", "profit", "income", "amount", "cost", "price")) else "number"

    @staticmethod
    def _choose_date_column(frame: pd.DataFrame) -> tuple[Any | None, pd.Series | None]:
        candidates = [column for column in frame.columns if any(token in str(column).lower() for token in ("date", "month", "time"))]
        best: tuple[Any | None, pd.Series | None, float] = (None, None, 0.0)
        for column in candidates:
            parsed = pd.to_datetime(frame[column], errors="coerce")
            ratio = float(parsed.notna().mean())
            if ratio > best[2] and parsed.dropna().nunique() > 1:
                best = (column, parsed, ratio)
        return best[0], best[1]

    @classmethod
    def _rank_category_dimensions(cls, frame: pd.DataFrame, columns: list[Any]) -> list[Any]:
        priorities = {"region": 100, "category": 95, "segment": 90, "product": 85, "channel": 80, "division": 75, "country": 70, "city": 60, "tier": 55, "status": 45, "payment": 40}
        return sorted(columns, key=lambda column: (-max((weight for token, weight in priorities.items() if token in str(column).lower()), default=0), frame[column].nunique(dropna=True), str(column)))

    @classmethod
    def _histogram_rows(cls, values: pd.Series) -> list[dict[str, Any]]:
        bins = pd.cut(values, bins=min(12, max(2, values.nunique())), include_lowest=True)
        counts = bins.value_counts().sort_index()
        return [{"category": str(interval), "value": int(count)} for interval, count in counts.items()]

    @staticmethod
    def _choose_numeric_measure(columns: list[Any]) -> Any:
        """Choose a business measure by semantic priority, not CSV column order."""
        priorities = (
            ("revenue", 100),
            ("sales", 95),
            ("profit", 90),
            ("income", 88),
            ("gross_amount", 84),
            ("amount", 82),
            ("value", 78),
            ("cost", 65),
            ("price", 45),
            ("quantity", 30),
        )

        def score(column: Any) -> tuple[int, int]:
            name = str(column).lower().replace(" ", "_")
            if "percent" in name or "percentage" in name or "rate" in name or name.endswith("_id") or name == "id":
                return (-1, 0)
            matches = [(weight, len(token)) for token, weight in priorities if token in name]
            if not matches:
                return (0, 0)
            weight, token_length = max(matches)
            # Prefer an exact semantic column over a generic token match.
            exact_bonus = 10 if name in {token for token, _ in priorities} else 0
            return (weight + exact_bonus, token_length)

        return max(columns, key=score)

    @classmethod
    def _choose_measure_for_question(cls, question: str, columns: list[Any]) -> Any:
        """Prefer a numeric field named by the user, then fall back to the business measure."""
        measure_columns = [column for column in columns if not cls._is_temporal_column(column)]
        # Calendar fields such as numeric ``year`` are dimensions, not measures.
        if not measure_columns:
            measure_columns = columns
        lowered = re.sub(r"[^a-z0-9]+", " ", question.lower())
        requested = [
            column for column in measure_columns
            if re.sub(r"[^a-z0-9]+", " ", str(column).lower()).strip() in lowered
        ]
        if requested:
            return requested[0]

        aliases = {
            "customer": ("customer", "client"),
            "revenue": ("revenue", "sales"),
            "profit": ("profit", "income"),
            "ticket": ("ticket",),
            "order": ("order",),
            "quantity": ("quantity", "units"),
        }
        for phrase, tokens in aliases.items():
            if phrase in lowered:
                match = next((column for column in measure_columns if any(token in str(column).lower() for token in tokens)), None)
                if match is not None:
                    return match
        return cls._choose_numeric_measure(measure_columns)

    @classmethod
    def _choose_measures_for_question(cls, question: str, columns: list[Any]) -> list[Any]:
        """Return all explicitly requested numeric measures for multi-series charts."""
        normalized_question = cls._normalize_label(question)
        matches = [
            column for column in columns
            if not cls._is_temporal_column(column)
            and cls._normalize_label(column)
            and cls._normalize_label(column) in normalized_question
        ]
        if len(matches) >= 2:
            return matches[:8]
        if re.search(r"\bmulti[\s-]?line\b", question.lower()):
            candidates = [column for column in columns if not cls._is_temporal_column(column)]
            priorities = (
                "revenue", "profit", "sales", "income", "cost", "units",
                "quantity", "customer", "marketing", "ticket", "nps", "price",
            )
            ranked = sorted(
                candidates,
                key=lambda column: (
                    next((index for index, token in enumerate(priorities) if token in str(column).lower()), len(priorities)),
                    str(column).lower(),
                ),
            )
            if len(ranked) >= 2:
                return ranked[:4]
        return [cls._choose_measure_for_question(question, columns)]

    @staticmethod
    def _choose_category_dimension(frame: pd.DataFrame, columns: list[Any]) -> Any:
        return PandasAIService._rank_category_dimensions(frame, columns)[0]

    @classmethod
    def _requested_category_dimension(cls, question: str, frame: pd.DataFrame, columns: list[Any]) -> Any:
        """Honor an explicit dimension; otherwise match the dashboard's stable default."""
        normalized_question = re.sub(r"[^a-z0-9]+", " ", question.lower()).strip()
        for column in cls._rank_category_dimensions(frame, columns):
            normalized_column = re.sub(r"[^a-z0-9]+", " ", str(column).lower()).strip()
            if normalized_column and normalized_column in normalized_question:
                return column
        return cls._choose_category_dimension(frame, columns)

    def chat(self, session_id: str, question: str) -> ChatResponse:
        session = self.sessions.get(session_id)
        if session is None:
            raise KeyError("Dataset session was not found.")

        if self._is_table_request(question):
            return self._build_table_response(session_id, question, session.source_dataframe)
        if self._is_chart_request(question):
            return self._build_interactive_chart(session_id, question, session.source_dataframe)

        sanitized_question = self._prepare_question(question)
        response = session.agent.chat(sanitized_question)
        # Never expose PandasAI's static PNG result to the product UI. If an
        # unrecognized chart wording reaches the LLM and it still returns a
        # chart, regenerate it through the interactive ECharts path.
        if getattr(response, "type", None) == "chart":
            return self._build_interactive_chart(session_id, question, session.source_dataframe)
        return self._serialize_response(session_id, response)

    @staticmethod
    def _is_chart_request(question: str) -> bool:
        chart_words = ("chart", "plot", "graph", "visual", "visualize", "visualise", "trend", "distribution", "histogram", "scatter", "heatmap", "heat map", "candlestick", "candle stick", "ohlc", "pie", "donut", "doughnut", "box", "bar", "line", "area")
        lowered = question.lower()
        return any(re.search(rf"\b{re.escape(word)}\b", lowered) for word in chart_words)

    @staticmethod
    def _is_table_request(question: str) -> bool:
        lowered = question.lower()
        return "table" in lowered or "tabular" in lowered or "top rows" in lowered

    def _build_table_response(self, session_id: str, question: str, frame: pd.DataFrame) -> ChatResponse:
        lowered = question.lower()
        limit = self._requested_limit(question)
        date_columns = [column for column in frame.columns if self._parse_date(column)]

        if "particulars" in [str(column).lower() for column in frame.columns] and len(date_columns) >= 3:
            particulars_column = next(column for column in frame.columns if str(column).lower() == "particulars")
            # Keep explicitly requested summary rows such as "Total Liquid".
            # The dashboard excludes total rows for aggregate charts, but a
            # chat request may intentionally target one of those rows.
            clean = frame.rename(columns={particulars_column: "Particulars"}).dropna(how="all").copy()
            clean = clean[clean["Particulars"].astype(str).str.strip().ne("")]
            latest_date = max(date_columns, key=self._parse_date)
            values = pd.to_numeric(clean[latest_date], errors="coerce")
            grouped = pd.DataFrame({"Category": clean["Particulars"].astype(str), "Total Value": values}).dropna()
            grouped = grouped.groupby("Category", as_index=False)["Total Value"].sum().sort_values("Total Value", ascending=False)
            if limit is not None:
                grouped = grouped.head(limit)
            rows = [{"Category": str(row["Category"]), "Total Value": self._number(row["Total Value"])} for _, row in grouped.iterrows()]
        else:
            frame, date_scope = self._apply_question_date_filter(frame, question)
            numeric_columns = frame.select_dtypes(include="number").columns.tolist()
            category_columns = [column for column in frame.select_dtypes(exclude="number").columns.tolist() if not self._is_identifier_column(column)]
            if not numeric_columns or not category_columns:
                raise ValueError("A table ranking requires at least one numeric measure and one categorical column.")
            measure = self._choose_measure_for_question(question, numeric_columns)
            dimensions = self._rank_category_dimensions(frame, category_columns)
            dimension = next((column for column in dimensions if str(column).lower() in lowered), dimensions[0])
            values = pd.to_numeric(frame[measure], errors="coerce")
            grouped = pd.DataFrame({"Category": frame[dimension].astype(str), f"Total {measure}": values}).dropna()
            grouped = grouped.groupby("Category", as_index=False)[f"Total {measure}"].sum().sort_values(f"Total {measure}", ascending=False)
            if limit is not None:
                grouped = grouped.head(limit)
            rows = [{"Category": str(row["Category"]), f"Total {measure}": self._number(row[f"Total {measure}"])} for _, row in grouped.iterrows()]

        return ChatResponse(session_id=session_id, type="dataframe", value=rows, message="Table generated from the detected dataset schema.", created_at=utc_now())

    @staticmethod
    def _requested_chart_kind(question: str) -> str:
        """Return the explicit chart intent so unsupported requests never silently become line charts."""
        lowered = question.lower()
        if "candlestick" in lowered or "ohlc" in lowered:
            return "candlestick"
        if "heatmap" in lowered or "heat map" in lowered:
            return "heatmap"
        if "histogram" in lowered:
            return "histogram"
        if "scatter" in lowered:
            return "scatter"
        if "box plot" in lowered or "boxplot" in lowered:
            return "box"
        if "distribution" in lowered:
            return "box"
        if "donut" in lowered or "doughnut" in lowered:
            return "donut"
        if "pie" in lowered:
            return "pie"
        if "area" in lowered:
            return "area"
        if "bar" in lowered or "column" in lowered:
            return "bar"
        if "line" in lowered or "trend" in lowered:
            return "line"
        return "line"

    @staticmethod
    def _requested_limit(question: str, default: int | None = None) -> int | None:
        """Read an explicit user limit; return None when the user did not request one."""
        lowered = question.lower()
        match = re.search(r"\btop\s+(\d+)\b|\b(?:first|show)\s+(\d+)\s+(?:categories|accounts|items|products|regions|segments)\b", lowered)
        if not match:
            return default
        return max(1, int(next(value for value in match.groups() if value)))

    @staticmethod
    def _normalize_label(value: Any) -> str:
        return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()

    def _apply_question_date_filter(self, frame: pd.DataFrame, question: str) -> tuple[pd.DataFrame, str | None]:
        """Apply an explicit year/date filter before any aggregation.

        Chart and table requests must not silently ignore a time constraint.  The
        deterministic chart path previously grouped the complete dataset even
        when the question contained a year such as ``for 2025 only``.
        """
        years = [int(value) for value in re.findall(r"\b(?:19|20)\d{2}\b", question)]
        date_column, parsed_dates = self._choose_date_column(frame)
        if not years:
            return frame, None
        if date_column is None or parsed_dates is None:
            raise ValueError("The requested year filter cannot be applied because no date column was detected.")

        start_year = min(years)
        end_year = max(years)
        mask = parsed_dates.dt.year.between(start_year, end_year)
        filtered = frame.loc[mask].copy()
        if filtered.empty:
            raise ValueError(f"No rows were found for the requested year range {start_year}-{end_year}.")
        scope = str(start_year) if start_year == end_year else f"{start_year}-{end_year}"
        return filtered, scope

    def _build_interactive_chart(self, session_id: str, question: str, frame: pd.DataFrame) -> ChatResponse:
        lowered = question.lower()
        chart_kind = self._requested_chart_kind(question)
        requested_limit = self._requested_limit(question)
        date_columns = [column for column in frame.columns if self._parse_date(column)]
        if "particulars" in frame.columns.str.lower().tolist() and len(date_columns) >= 3:
            particulars_column = next(column for column in frame.columns if str(column).lower() == "particulars")
            # Preserve summary rows because a user may explicitly request
            # one, for example "Total Liquid by date".
            clean = frame.rename(columns={particulars_column: "Particulars"}).dropna(how="all").copy()
            clean = clean[clean["Particulars"].astype(str).str.strip().ne("")]
            ordered_dates = sorted(date_columns, key=lambda column: self._parse_date(column))
            long = clean.melt(id_vars=["Particulars"], value_vars=ordered_dates, var_name="date", value_name="value")
            long["date"] = long["date"].map(self._parse_date)
            long["value"] = pd.to_numeric(long["value"], errors="coerce")
            long = long.dropna(subset=["date", "value"])
            names = long["Particulars"].drop_duplicates().tolist()
            normalized_question = self._normalize_label(question)
            requested_names = [
                name for name in names
                if self._normalize_label(name) and self._normalize_label(name) in normalized_question
            ]
            if requested_names:
                account = requested_names[0]
                analysis_long = long
                account_data = long[long["Particulars"] == account].sort_values("date")
            else:
                if any(term in normalized_question for term in ("financial row", "particulars", "account", "series")):
                    examples = ", ".join(str(name) for name in names[:8])
                    raise ValueError(
                        "I could not safely identify the financial row for this chart. "
                        f"Specify the exact Particulars label, for example: {examples}."
                    )
                # A generic time-series request must not guess an account.
                # Use only detail rows and label the result as an aggregate.
                detail = self._clean_rows(clean)
                analysis_long = detail.melt(id_vars=["Particulars"], value_vars=ordered_dates, var_name="date", value_name="value")
                analysis_long["date"] = analysis_long["date"].map(self._parse_date)
                analysis_long["value"] = pd.to_numeric(analysis_long["value"], errors="coerce")
                analysis_long = analysis_long.dropna(subset=["date", "value"])
                account = "Total daily value"
                account_data = analysis_long.groupby("date", as_index=False)["value"].sum()
                account_data["Particulars"] = account
                account_data = account_data.sort_values("date")

            if chart_kind in {"pie", "donut"}:
                latest_date = analysis_long["date"].max()
                distribution = analysis_long[analysis_long["date"] == latest_date].groupby("Particulars", as_index=False)["value"].sum()
                distribution = distribution[distribution["value"] > 0].sort_values("value", ascending=False)
                top = distribution.head(requested_limit).copy()
                if len(distribution) > len(top):
                    other_value = distribution.iloc[len(top):]["value"].sum()
                    top = pd.concat([top, pd.DataFrame([{ "Particulars": "Other", "value": other_value }])], ignore_index=True)
                data = [{"name": str(row.Particulars), "value": self._number(row.value)} for row in top.itertuples(index=False)]
                spec = {"kind": chart_kind, "title": f"Money distribution by account — {latest_date.strftime('%d %b %Y')}", "data": data, "format": "INR", "as_of": latest_date.strftime("%Y-%m-%d")}
            elif chart_kind == "candlestick":
                ohlc = account_data.set_index("date")["value"].resample("W-MON").agg(Open="first", High="max", Low="min", Close="last").dropna().reset_index()
                data = [{"date": row.date.strftime("%Y-%m-%d"), "open": self._number(row.Open), "high": self._number(row.High), "low": self._number(row.Low), "close": self._number(row.Close)} for row in ohlc.itertuples(index=False)]
                spec = {"kind": "candlestick", "title": f"Weekly financial movement — {account}", "data": data, "x_axis": "date", "y_axis": "value", "format": "INR"}
            elif chart_kind == "bar":
                grouped = analysis_long.groupby("Particulars", as_index=False)["value"].mean().sort_values("value", ascending=False).head(requested_limit)
                spec = {"kind": "bar", "title": "Average daily value by account", "data": [{"category": str(row.Particulars), "value": self._number(row.value)} for row in grouped.itertuples(index=False)], "x_axis": "category", "y_axis": "value", "format": "INR"}
            elif chart_kind in {"line", "area"}:
                spec = {"kind": "line", "title": f"Daily value trend — {account}", "data": [{"date": row.date.strftime("%Y-%m-%d"), "value": self._number(row.value)} for row in account_data.itertuples(index=False)], "x_axis": "date", "y_axis": "value", "format": "INR"}
                if chart_kind == "area":
                    spec["kind"] = "area"
                if re.search(r"\bmulti[\s-]?line\b", question.lower()) and not requested_names:
                    series_names = (
                        analysis_long.groupby("Particulars", as_index=False)["value"]
                        .mean()
                        .sort_values("value", ascending=False)
                        .head(6)["Particulars"]
                        .tolist()
                    )
                    multi_rows = analysis_long[analysis_long["Particulars"].isin(series_names)].sort_values("date")
                    spec = {
                        "kind": "line",
                        "title": "Multiple account trends",
                        "data": [{"date": row.date.strftime("%Y-%m-%d"), "series": str(row.Particulars), "value": self._number(row.value)} for row in multi_rows.itertuples(index=False)],
                        "series_key": "series",
                        "x_axis": "date",
                        "y_axis": "value",
                        "format": "INR",
                    }
            elif chart_kind == "scatter":
                spec = {"kind": "scatter", "title": f"Value observations — {account}", "data": [{"x": index + 1, "y": self._number(row.value), "label": row.date.strftime("%Y-%m-%d")} for index, row in enumerate(account_data.itertuples(index=False))], "x_axis": "Observation", "y_axis": "Value", "format": "INR"}
            elif chart_kind == "histogram":
                values = account_data["value"]
                bins = pd.cut(values, bins=min(10, max(2, values.nunique())), include_lowest=True)
                counts = bins.value_counts().sort_index()
                spec = {"kind": "histogram", "title": f"Value distribution — {account}", "data": [{"category": str(interval), "value": int(count)} for interval, count in counts.items()], "x_axis": "Value range", "y_axis": "Count", "format": "number"}
            elif chart_kind == "box":
                spec = {"kind": "box", "title": f"Value spread — {account}", "data": [{"name": account, "value": [self._number(value) for value in account_data["value"].tolist()]}], "format": "INR"}
            elif chart_kind == "heatmap":
                pivot = analysis_long.pivot_table(index="Particulars", columns="date", values="value", aggfunc="mean").fillna(0)
                corr = pivot.T.corr().fillna(0).iloc[:12, :12]
                labels = [str(label) for label in corr.index]
                spec = {"kind": "heatmap", "title": "Account movement correlation", "x_labels": labels, "y_labels": labels, "data": [{"x": x, "y": y, "value": self._number(corr.iloc[y, x])} for y in range(len(labels)) for x in range(len(labels))], "format": "number"}
            else:
                raise ValueError(f"The {chart_kind} chart needs a tabular dataset or additional chart-specific fields. Supported charts for this financial layout are pie, bar, line, area, and candlestick.")
        else:
            frame, date_scope = self._apply_question_date_filter(frame, question)
            numeric_columns = frame.select_dtypes(include="number").columns.tolist()
            category_columns = frame.select_dtypes(exclude="number").columns.tolist()
            if not numeric_columns:
                raise ValueError("No numeric columns are available for an interactive chart.")
            measures = self._choose_measures_for_question(question, numeric_columns)
            measure = measures[0]
            if chart_kind in {"pie", "donut"}:
                category = self._requested_category_dimension(question, frame, category_columns) if category_columns else None
                if category is None:
                    raise ValueError("A categorical column is required for a pie chart.")
                grouped = frame.assign(_metric=pd.to_numeric(frame[measure], errors="coerce")).groupby(category, as_index=False)["_metric"].sum()
                grouped = grouped[grouped["_metric"] > 0].sort_values("_metric", ascending=False)
                top = grouped.head(requested_limit).copy()
                if len(grouped) > len(top):
                    other_value = grouped.iloc[len(top):]["_metric"].sum()
                    top = pd.concat([top, pd.DataFrame([{category: "Other", "_metric": other_value}])], ignore_index=True)
                title = f"{measure} distribution by {category}"
                if date_scope:
                    title += f" ({date_scope})"
                spec = {"kind": chart_kind, "title": title, "data": [{"name": str(row[category]), "value": self._number(row["_metric"])} for _, row in top.iterrows()], "format": "number"}
            elif chart_kind == "bar":
                group_frame = frame.copy()
                period_dimension = None
                period_phrase = None
                if re.search(r"\bby\s+year\b|\byearly\b|\bper\s+year\b", lowered):
                    year_column = next((column for column in frame.columns if str(column).lower() == "year"), None)
                    if year_column is not None:
                        group_frame["_chart_period"] = pd.to_numeric(frame[year_column], errors="coerce")
                    else:
                        date_column, parsed_dates = self._choose_date_column(frame)
                        if date_column is None or parsed_dates is None:
                            raise ValueError("A year/date column is required for a chart grouped by year.")
                        group_frame["_chart_period"] = parsed_dates.dt.year
                    period_dimension = "_chart_period"
                    period_phrase = "Year"
                elif re.search(r"\bby\s+month\b|\bmonthly\b|\bper\s+month\b", lowered):
                    date_column, parsed_dates = self._choose_date_column(frame)
                    if date_column is None or parsed_dates is None:
                        raise ValueError("A date column is required for a chart grouped by month.")
                    group_frame["_chart_period"] = parsed_dates.dt.to_period("M").astype(str)
                    period_dimension = "_chart_period"
                    period_phrase = "Month"

                category = period_dimension or (self._requested_category_dimension(question, frame, category_columns) if category_columns else None)
                if category is None:
                    raise ValueError("A categorical column is required for a bar chart.")
                grouped = group_frame.assign(_metric=pd.to_numeric(group_frame[measure], errors="coerce")).groupby(category, as_index=False)["_metric"].sum().sort_values("_metric", ascending=False).head(requested_limit)
                title = f"{measure} by {period_phrase}" if period_phrase else f"Top {category} by {measure}"
                if date_scope:
                    title += f" ({date_scope})"
                spec = {"kind": "bar", "title": title, "data": [{"category": str(row[category]), "value": self._number(row["_metric"])} for _, row in grouped.iterrows()], "x_axis": "category", "y_axis": "value", "format": "number"}
            elif chart_kind in {"line", "area"}:
                date_column, parsed_dates = self._choose_date_column(frame)
                if date_column is not None and parsed_dates is not None:
                    if any(token in lowered for token in ("by year", "yearly", "annual", "per year")):
                        period_values = parsed_dates.dt.year.astype(str)
                        period_label = "Year"
                    elif any(token in lowered for token in ("by month", "monthly", "per month")):
                        period_values = parsed_dates.dt.to_period("M").astype(str)
                        period_label = "Month"
                    else:
                        period_values = parsed_dates.dt.strftime("%Y-%m-%d")
                        period_label = "Date"

                    normalized_question = self._normalize_label(question)
                    series_dimension = next(
                        (
                            column for column in category_columns
                            if column != date_column
                            and self._normalize_label(column)
                            and self._normalize_label(column) in normalized_question
                        ),
                        None,
                    )

                    if series_dimension is not None and len(measures) == 1:
                        series_frame = pd.DataFrame({"_period": period_values, "_series": frame[series_dimension].astype(str), "_metric": pd.to_numeric(frame[measure], errors="coerce")}).dropna()
                        grouped = series_frame.groupby(["_period", "_series"], as_index=False)["_metric"].sum()
                        rows = [{"period": str(row["_period"]), "series": str(row["_series"]), "value": self._number(row["_metric"])} for _, row in grouped.iterrows()]
                        title = f"{measure} by {period_label} and {series_dimension}"
                        if date_scope:
                            title += f" ({date_scope})"
                        spec = {"kind": "line", "title": title, "data": rows, "series_key": "series", "x_axis": "period", "y_axis": "value", "format": "number"}
                    elif len(measures) > 1:
                        rows = []
                        for selected_measure in measures:
                            series_frame = pd.DataFrame({"_period": period_values, "_metric": pd.to_numeric(frame[selected_measure], errors="coerce")}).dropna()
                            grouped = series_frame.groupby("_period", as_index=False)["_metric"].sum()
                            rows.extend({"period": str(row["_period"]), "series": str(selected_measure), "value": self._number(row["_metric"])} for _, row in grouped.iterrows())
                        title = f"{', '.join(str(item) for item in measures)} by {period_label}"
                        if date_scope:
                            title += f" ({date_scope})"
                        spec = {"kind": "line", "title": title, "data": rows, "series_key": "series", "x_axis": "period", "y_axis": "value", "format": "number"}
                    else:
                        trend_frame = pd.DataFrame({"_date": parsed_dates, "_metric": pd.to_numeric(frame[measure], errors="coerce"), "_period": period_values}).dropna()
                        # If the user asks for customers but there is no numeric
                        # customer measure, count unique customer identifiers.
                        if "customer" in lowered or "client" in lowered:
                            customer_column = next((column for column in frame.columns if any(token in str(column).lower() for token in ("customer", "client"))), None)
                            if customer_column is not None and not any(token in str(measure).lower() for token in ("customer", "client")):
                                count_frame = pd.DataFrame({"_period": period_values, "_customer": frame[customer_column].astype(str)}).dropna()
                                grouped = count_frame.groupby("_period", as_index=False)["_customer"].nunique()
                                rows = [{"period": str(row["_period"]), "series": "New customers", "value": int(row["_customer"])} for _, row in grouped.iterrows()]
                                y_axis = "Customers"
                            else:
                                grouped = trend_frame.groupby("_period", as_index=False)["_metric"].sum()
                                rows = [{"period": str(row["_period"]), "series": str(measure), "value": self._number(row["_metric"])} for _, row in grouped.iterrows()]
                                y_axis = str(measure)
                        else:
                            grouped = trend_frame.groupby("_period", as_index=False)["_metric"].sum()
                            rows = [{"period": str(row["_period"]), "series": str(measure), "value": self._number(row["_metric"])} for _, row in grouped.iterrows()]
                            y_axis = str(measure)
                        title = f"{y_axis} by {period_label}"
                        if date_scope:
                            title += f" ({date_scope})"
                        spec = {"kind": "line", "title": title, "data": rows, "x_axis": "period", "y_axis": y_axis, "format": "number"}
                else:
                    spec = {"kind": "line", "title": f"{measure} trend", "data": [{"index": index + 1, "value": self._number(value)} for index, value in enumerate(pd.to_numeric(frame[measure], errors="coerce").dropna().head(100))], "x_axis": "index", "y_axis": str(measure), "format": "number"}
                if chart_kind == "area":
                    spec["kind"] = "area"
            elif chart_kind == "scatter":
                scatter_columns = [column for column in numeric_columns if column != measure]
                x_column = scatter_columns[0] if scatter_columns else measure
                values = frame[[x_column, measure]].apply(pd.to_numeric, errors="coerce").dropna().head(2000)
                title = f"{measure} vs {x_column}"
                if date_scope:
                    title += f" ({date_scope})"
                spec = {"kind": "scatter", "title": title, "data": [{"x": self._number(row[x_column]), "y": self._number(row[measure])} for _, row in values.iterrows()], "x_axis": str(x_column), "y_axis": str(measure), "format": "number"}
            elif chart_kind == "histogram":
                values = pd.to_numeric(frame[measure], errors="coerce").dropna()
                bins = pd.cut(values, bins=min(15, max(2, values.nunique())), include_lowest=True)
                counts = bins.value_counts().sort_index()
                title = f"Distribution of {measure}"
                if date_scope:
                    title += f" ({date_scope})"
                spec = {"kind": "histogram", "title": title, "data": [{"category": str(interval), "value": int(count)} for interval, count in counts.items()], "x_axis": str(measure), "y_axis": "Count", "format": "number"}
            elif chart_kind == "box":
                values = pd.to_numeric(frame[measure], errors="coerce").dropna()
                if category_columns:
                    category = self._requested_category_dimension(question, frame, category_columns)
                    groups = frame.assign(_metric=pd.to_numeric(frame[measure], errors="coerce")).dropna(subset=["_metric"]).groupby(category)
                    box_data = [{"name": str(name), "value": [self._number(value) for value in group["_metric"].tolist()]} for name, group in list(groups)[:12]]
                else:
                    box_data = [{"name": str(measure), "value": [self._number(value) for value in values.tolist()]}]
                title = f"Distribution of {measure}"
                if date_scope:
                    title += f" ({date_scope})"
                spec = {"kind": "box", "title": title, "data": box_data, "format": "number"}
            elif chart_kind == "heatmap":
                columns = [column for column in numeric_columns if not self._is_temporal_column(column)][:12]
                if len(columns) < 2:
                    raise ValueError("A heatmap requires at least two non-temporal numeric measures.")
                corr = frame[columns].corr().fillna(0)
                labels = [str(label) for label in corr.index]
                title = "Numeric measure correlation"
                if date_scope:
                    title += f" ({date_scope})"
                spec = {"kind": "heatmap", "title": title, "x_labels": labels, "y_labels": labels, "data": [{"x": x, "y": y, "value": self._number(corr.iloc[y, x])} for y in range(len(labels)) for x in range(len(labels))], "format": "number"}
            else:
                raise ValueError(f"The {chart_kind} chart is not yet supported for this dataset shape. Choose pie, bar, line, area, or upload data with clear numeric and category columns.")

        return ChatResponse(session_id=session_id, type="chart_spec", value=spec, message="Interactive chart generated successfully.", created_at=utc_now())

    def delete_dataset(self, session_id: str) -> None:
        session = self.sessions.delete(session_id)
        if session is None:
            raise KeyError("Dataset session was not found.")
        Path(session.upload_path).unlink(missing_ok=True)
        for chart_path in self.settings.chart_directory.glob(f"{session_id}-*"):
            if chart_path.is_file():
                chart_path.unlink(missing_ok=True)

    def _load_dataframe(self, path: Path, extension: str) -> pd.DataFrame:
        if extension == ".csv":
            return pd.read_csv(path)
        return pd.read_excel(path)

    @staticmethod
    def _validate_dataframe(dataframe: pd.DataFrame) -> None:
        if dataframe.empty:
            raise ValueError("The uploaded dataset contains no rows.")
        if len(dataframe.columns) == 0:
            raise ValueError("The uploaded dataset contains no columns.")
        if dataframe.columns.duplicated().any():
            raise ValueError("Column names must be unique.")

    @staticmethod
    def _prepare_question(question: str) -> str:
        question = " ".join(question.split())
        return (
            f"{question}\n\n"
            "Use execute_sql_query for data access. Return a valid PandasAI result "
            "object. When using pandas.qcut on duplicate values, use duplicates='drop' "
            "without fixed labels or use rank-based bins with dynamically sized labels. "
            "Chart requests are handled by the application as interactive Apache ECharts "
            "specifications; do not create or return PNG, JPG, or SVG chart files."
        )

    def _serialize_response(self, session_id: str, response: Any) -> ChatResponse:
        response_type = getattr(response, "type", "string")
        value = getattr(response, "value", response)

        if response_type == "dataframe":
            if isinstance(value, pd.DataFrame):
                value = value.where(pd.notna(value), None).to_dict(orient="records")
            elif isinstance(value, pd.Series):
                value = value.where(pd.notna(value), None).to_dict()
        elif response_type == "chart":
            raise ValueError("Static chart responses are disabled. Use the interactive Apache ECharts chart path.")
        elif response_type == "number":
            value = float(value) if hasattr(value, "item") else value

        return ChatResponse(
            session_id=session_id,
            type=response_type,
            value=value,
            created_at=utc_now(),
        )

    def _persist_chart(self, value: Any, session_id: str) -> str:
        output_path = self.settings.chart_directory / f"{session_id}-{uuid.uuid4().hex}.png"
        if isinstance(value, str) and value.startswith("data:image"):
            encoded = value.split(",", 1)[1]
            output_path.write_bytes(base64.b64decode(encoded))
        elif isinstance(value, str):
            source = Path(value)
            if not source.exists():
                raise FileNotFoundError("PandasAI returned a chart path that does not exist.")
            shutil.copyfile(source, output_path)
        else:
            raise ValueError("PandasAI returned an unsupported chart value.")
        return f"/files/charts/{output_path.name}"

