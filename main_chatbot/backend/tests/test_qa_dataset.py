from pathlib import Path

from fastapi.testclient import TestClient

from main_chatbot.backend.main import app


client = TestClient(app)
QA_FILE = Path("data/qa_business_analytics.csv")


def test_qa_dataset_upload_profile_and_dashboard() -> None:
    with QA_FILE.open("rb") as dataset:
        response = client.post(
            "/datasets",
            files={"file": (QA_FILE.name, dataset, "text/csv")},
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["rows"] == 12
    session_id = payload["session_id"]

    dashboard = client.get(f"/sessions/{session_id}/dashboard")
    assert dashboard.status_code == 200
    dashboard_payload = dashboard.json()
    assert dashboard_payload["profile"]["primary_measure"] == "Revenue_USD"
    assert dashboard_payload["profile"]["date_column"] == "Order_Date"
    assert dashboard_payload["charts"]

    assert client.delete(f"/sessions/{session_id}").status_code == 204


def test_qa_dataset_table_and_chart_values() -> None:
    with QA_FILE.open("rb") as dataset:
        response = client.post(
            "/datasets",
            files={"file": (QA_FILE.name, dataset, "text/csv")},
        )

    assert response.status_code == 201
    session_id = response.json()["session_id"]

    table = client.post(
        f"/sessions/{session_id}/chat",
        json={"question": "Show the top 3 regions by total revenue in a table."},
    )
    assert table.status_code == 200
    assert table.json()["type"] == "dataframe"
    assert table.json()["value"] == [
        {"Category": "North", "Total Revenue_USD": 5900},
        {"Category": "South", "Total Revenue_USD": 5400},
        {"Category": "East", "Total Revenue_USD": 5350},
    ]

    pie = client.post(
        f"/sessions/{session_id}/chat",
        json={"question": "Create a pie chart of Revenue_USD by Region."},
    )
    assert pie.status_code == 200
    assert pie.json()["type"] == "chart_spec"
    assert pie.json()["value"]["kind"] == "pie"
    assert {item["name"]: item["value"] for item in pie.json()["value"]["data"]} == {
        "North": 5900,
        "South": 5400,
        "East": 5350,
    }

    multi_line = client.post(
        f"/sessions/{session_id}/chat",
        json={"question": "Show Revenue_USD and Profit_USD by month in a line chart."},
    )
    assert multi_line.status_code == 200
    multi_line_payload = multi_line.json()
    assert multi_line_payload["type"] == "chart_spec"
    assert multi_line_payload["value"]["series_key"] == "series"
    assert {row["series"] for row in multi_line_payload["value"]["data"]} == {
        "Revenue_USD",
        "Profit_USD",
    }
    revenue_rows = [
        row for row in multi_line_payload["value"]["data"]
        if row["series"] == "Revenue_USD"
    ]
    assert sum(row["value"] for row in revenue_rows) == 16650

    generic_multi_line = client.post(
        f"/sessions/{session_id}/chat",
        json={"question": "Generate a multiline graph on this dataset."},
    )
    assert generic_multi_line.status_code == 200
    generic_multi_line_payload = generic_multi_line.json()["value"]
    assert generic_multi_line_payload["series_key"] == "series"
    assert len({row["series"] for row in generic_multi_line_payload["data"]}) >= 2

    product_lines = client.post(
        f"/sessions/{session_id}/chat",
        json={"question": "Create a monthly revenue_usd chart for each product_line."},
    )
    assert product_lines.status_code == 200
    product_line_payload = product_lines.json()["value"]
    assert product_line_payload["series_key"] == "series"
    assert {row["series"] for row in product_line_payload["data"]} == {
        "Alpha",
        "Beta",
        "Gamma",
    }
    product_totals = {}
    for row in product_line_payload["data"]:
        product_totals[row["series"]] = product_totals.get(row["series"], 0) + row["value"]
    assert product_totals == {"Alpha": 6650, "Beta": 6000, "Gamma": 4000}

    box = client.post(
        f"/sessions/{session_id}/chat",
        json={"question": "Create a box plot of Profit_USD by Product_Line."},
    )
    assert box.status_code == 200
    assert box.json()["value"]["kind"] == "box"
    assert {item["name"] for item in box.json()["value"]["data"]} == {
        "Alpha",
        "Beta",
        "Gamma",
    }

    assert client.delete(f"/sessions/{session_id}").status_code == 204


def test_explicit_year_filter_is_applied_before_bar_aggregation() -> None:
    csv = b"""Order_Date,year,Region,Revenue_USD
2025-01-15,2025,North,100
2025-02-15,2025,South,200
2025-03-15,2025,North,300
2026-01-15,2026,North,900
2026-02-15,2026,South,800
"""
    response = client.post(
        "/datasets",
        files={"file": ("year-filter.csv", csv, "text/csv")},
    )
    assert response.status_code == 201
    session_id = response.json()["session_id"]

    chart = client.post(
        f"/sessions/{session_id}/chat",
        json={"question": "Create a bar chart showing total revenue_usd by region for the year 2025 only."},
    )
    assert chart.status_code == 200
    payload = chart.json()["value"]
    assert payload["title"].endswith("(2025)")
    assert {item["category"]: item["value"] for item in payload["data"]} == {
        "North": 400,
        "South": 200,
    }

    yearly = client.post(
        f"/sessions/{session_id}/chat",
        json={"question": "Create a bar chart of total revenue_usd by year."},
    )
    assert yearly.status_code == 200
    yearly_payload = yearly.json()["value"]
    assert yearly_payload["title"].lower() == "revenue_usd by year"
    assert {item["category"]: item["value"] for item in yearly_payload["data"]} == {
        "2025": 600,
        "2026": 1700,
    }

    assert client.delete(f"/sessions/{session_id}").status_code == 204
