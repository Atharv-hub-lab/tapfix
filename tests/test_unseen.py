from app.main import app
from fastapi.testclient import TestClient


with TestClient(app) as client:
    response = client.post(
        "/v1/troubleshoot",
        json={
            "query": "My phone has a strange problem I cannot identify",
            "siis_response": {
                "title": "Unknown device issue",
                "content": "Check the device and follow the available troubleshooting guidance.",
            },
        },
    )

    print("STATUS:", response.status_code)
    print(response.text)