from fastapi.testclient import TestClient

from main_chatbot.backend.main import app


client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_upload_and_delete_dataset() -> None:
    with open("data/dataset.csv", "rb") as dataset:
        response = client.post(
            "/datasets",
            files={"file": ("dataset.csv", dataset, "text/csv")},
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["rows"] == 500
    assert "Region" in payload["columns"]

    dashboard = client.get(f"/sessions/{payload['session_id']}/dashboard")
    assert dashboard.status_code == 200
    dashboard_payload = dashboard.json()
    assert dashboard_payload["type"] == "dashboard"
    assert len(dashboard_payload["kpis"]) >= 1
    assert len(dashboard_payload["charts"]) >= 4
    assert dashboard_payload["profile"]["primary_measure"] == "Net_Revenue_INR"
    assert dashboard_payload["profile"]["date_column"] == "Order_Date"

    chart = client.post(
        f"/sessions/{payload['session_id']}/chat",
        json={"question": "Create a line chart of Profit_INR by Region."},
    )
    assert chart.status_code == 200
    assert chart.json()["type"] == "chart_spec"

    multi_line = client.post(
        f"/sessions/{payload['session_id']}/chat",
        json={"question": "Show Net_Revenue_INR and Profit_INR by month in a line chart."},
    )
    assert multi_line.status_code == 200
    assert multi_line.json()["value"]["kind"] == "line"
    assert multi_line.json()["value"]["series_key"] == "series"
    assert {row["series"] for row in multi_line.json()["value"]["data"]} == {"Net_Revenue_INR", "Profit_INR"}

    pie = client.post(
        f"/sessions/{payload['session_id']}/chat",
        json={"question": "Create a pie chart of total Profit_INR by Region."},
    )
    assert pie.status_code == 200
    assert pie.json()["value"]["kind"] == "pie"
    assert pie.json()["value"]["data"]

    top_five = client.post(
        f"/sessions/{payload['session_id']}/chat",
        json={"question": "Show the top 5 categories by total revenue in a pie chart."},
    )
    assert top_five.status_code == 200
    assert len(top_five.json()["value"]["data"]) <= 6

    distribution = client.post(
        f"/sessions/{payload['session_id']}/chat",
        json={"question": "Show revenue distribution by Region."},
    )
    assert distribution.status_code == 200
    assert distribution.json()["type"] == "chart_spec"
    assert distribution.json()["value"]["kind"] == "box"

    yearly_customers = client.post(
        f"/sessions/{payload['session_id']}/chat",
        json={"question": "Show new customers by year in a chart."},
    )
    assert yearly_customers.status_code == 200
    assert yearly_customers.json()["type"] == "chart_spec"
    assert yearly_customers.json()["value"]["kind"] == "line"

    top_seven_table = client.post(
        f"/sessions/{payload['session_id']}/chat",
        json={"question": "Show the top 7 categories by total revenue in a table."},
    )
    assert top_seven_table.status_code == 200
    assert top_seven_table.json()["type"] == "dataframe"
    assert 1 <= len(top_seven_table.json()["value"]) <= 7

    delete_response = client.delete(f"/sessions/{payload['session_id']}")
    assert delete_response.status_code == 204


def test_wide_financial_dashboard_has_same_chart_count() -> None:
    with open("data/Dummy.csv", "rb") as dataset:
        response = client.post(
            "/datasets",
            files={"file": ("Dummy.csv", dataset, "text/csv")},
        )

    assert response.status_code == 201
    session_id = response.json()["session_id"]
    dashboard = client.get(f"/sessions/{session_id}/dashboard")
    assert dashboard.status_code == 200
    assert len(dashboard.json()["charts"]) == 6
    assert dashboard.json()["charts"][3]["kind"] == "pie"
    total_liquid = client.post(
        f"/sessions/{session_id}/chat",
        json={"question": "Generate a chart that shows total liquid by date."},
    )
    assert total_liquid.status_code == 200
    assert total_liquid.json()["type"] == "chart_spec"
    assert "Total Liquid" in total_liquid.json()["value"]["title"]
    assert total_liquid.json()["value"]["data"][0]["value"] == 2400566

    generic_date = client.post(
        f"/sessions/{session_id}/chat",
        json={"question": "Generate a chart by date to demonstrate this dataset."},
    )
    assert generic_date.status_code == 200
    assert "Total daily value" in generic_date.json()["value"]["title"]

    unresolved = client.post(
        f"/sessions/{session_id}/chat",
        json={"question": "Generate a chart for an unknown financial row by date."},
    )
    assert unresolved.status_code == 422
    assert "exact Particulars label" in unresolved.json()["detail"]
    assert client.delete(f"/sessions/{session_id}").status_code == 204

