import json
import os
import sys
from unittest.mock import MagicMock

import pytest
import requests

BASE_URL = "http://localhost:5002"


def load_json(filename):
    path = os.path.join(os.path.dirname(__file__), f"../examples/model_cards/{filename}")
    with open(path, "r") as file:
        return json.load(file)


def load_datasheet_json(filename):
    path = os.path.join(os.path.dirname(__file__), f"../examples/datasheets/{filename}")
    with open(path, "r") as file:
        return json.load(file)


def dummy_response(status_code, json_data):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    return resp


@pytest.fixture
def client(monkeypatch):
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from legacy.legacy_server.server import app
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def test_upload_datasheet(monkeypatch):
    datasheet_data = load_datasheet_json("imagenet.json")
    dummy = dummy_response(200, {"message": "Successfully uploaded the datasheet"})
    monkeypatch.setattr(requests, "post", lambda url, json: dummy)
    response = requests.post(f"{BASE_URL}/datasheet", json=datasheet_data)
    assert response.status_code == 200
    assert "Successfully uploaded the datasheet" in response.json().get("message", "")


def test_upload_new_model_card(monkeypatch):
    data = load_json("tensorflow_titanic_MC.json")
    dummy = dummy_response(200, {"message": "Successfully uploaded the model card", "model_card_id": "dummy_id"})
    monkeypatch.setattr(requests, "post", lambda url, json: dummy)
    response = requests.post(f"{BASE_URL}/modelcard", json=data)
    assert response.status_code == 200
    assert "Successfully uploaded the model card" in response.json().get("message", "")


def test_upload_duplicate_model_card(monkeypatch):
    data = load_json("tesorflow_adult_nn_MC.json")
    responses = [
        dummy_response(200, {"message": "Successfully uploaded the model card", "model_card_id": "dummy_id"}),
        dummy_response(200, {"message": "Model card already exists", "model_card_id": "dummy_id"})
    ]
    call_count = 0

    def fake_post(url, json):
        nonlocal call_count
        resp = responses[call_count]
        call_count += 1
        return resp

    monkeypatch.setattr(requests, "post", fake_post)
    resp1 = requests.post(f"{BASE_URL}/modelcard", json=data)
    resp2 = requests.post(f"{BASE_URL}/modelcard", json=data)
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert "Model card already exists" in resp2.json().get("message", "")


def test_update_model_card(monkeypatch):
    data = load_json("tesorflow_adult_nn_MC.json")
    dummy = dummy_response(200, {"message": "Successfully updated the model card", "model_card_id": "dummy_id"})
    monkeypatch.setattr(requests, "put", lambda url, json: dummy)
    response = requests.put(f"{BASE_URL}/modelcard/dummy_id", json=data)
    assert response.status_code == 200
    assert "Successfully updated the model card" in response.json().get("message", "")


def test_download_model_card(monkeypatch):
    model_card_id = "dummy_model_card_id"
    dummy = dummy_response(200, {"external_id": "dummy_external_id"})
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: dummy)
    response = requests.get(f"{BASE_URL}/modelcard/{model_card_id}")
    assert response.status_code == 200
    assert "external_id" in response.json()


def test_download_url(monkeypatch):
    model_id = "dummy_model_id-model"
    dummy = dummy_response(200, {"download_url": "http://dummy-download-url"})
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: dummy)
    response = requests.get(f"{BASE_URL}/modelcard/{model_id}/download_url")
    assert response.status_code == 200
    assert "download_url" in response.json()


def test_list_models(monkeypatch):
    dummy = dummy_response(200, ["model1", "model2"])
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: dummy)
    response = requests.get(f"{BASE_URL}/modelcards")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_deployment_info(monkeypatch):
    model_id = "dummy_model_id-model"
    dummy = dummy_response(200, {"deployments": ["dep1", "dep2"]})
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: dummy)
    response = requests.get(f"{BASE_URL}/modelcard/{model_id}/deployments")
    assert response.status_code == 200


def test_update_model_location(monkeypatch):
    data = {"model_id": "dummy_model_id-model", "location": "http://new-location.com/model"}
    dummy = dummy_response(200, {"message": "Model location updated successfully"})
    monkeypatch.setattr(requests, "put", lambda url, json: dummy)
    response = requests.put(f"{BASE_URL}/modelcard/{data['model_id']}/location", json={"location": data['location']})
    assert response.status_code == 200
    assert "Model location updated successfully" in response.json().get("message", "")


def test_get_huggingface_credentials_success(client, monkeypatch):
    monkeypatch.setenv("HF_HUB_USERNAME", "hf_user")
    monkeypatch.setenv("HF_HUB_TOKEN", "hf_token")
    response = client.get("/modelcard/dummy/huggingface_credentials")
    assert response.status_code == 200
    data = response.get_json()
    assert data.get("username") == "hf_user"
    assert data.get("token") == "hf_token"


def test_get_huggingface_credentials_failure(client, monkeypatch):
    monkeypatch.delenv("HF_HUB_USERNAME", raising=False)
    monkeypatch.delenv("HF_HUB_TOKEN", raising=False)
    response = client.get("/modelcard/dummy/huggingface_credentials")
    assert response.status_code == 400
    data = response.get_json()
    assert "error" in data


def test_get_github_credentials_success(client, monkeypatch):
    monkeypatch.setenv("GH_HUB_USERNAME", "gh_user")
    monkeypatch.setenv("GH_HUB_TOKEN", "gh_token")
    response = client.get("/modelcard/dummy/github_credentials")
    assert response.status_code == 200
    data = response.get_json()
    assert data.get("username") == "gh_user"
    assert data.get("token") == "gh_token"


def test_get_github_credentials_failure(client, monkeypatch):
    monkeypatch.delenv("GH_HUB_USERNAME", raising=False)
    monkeypatch.delenv("GH_HUB_TOKEN", raising=False)
    response = client.get("/modelcard/dummy/github_credentials")
    assert response.status_code == 400
    data = response.get_json()
    assert "error" in data


def test_upload_model_card_with_deployment_info(monkeypatch):
    # Create a test model card with deployment information in ai_model section
    data = load_json("tesorflow_adult_nn_MC.json")
    # Add deployment strategy and testing information to ai_model section
    data["ai_model"]["deployment_strategy"] = "ultralytics"
    data["ai_model"]["deployment_tested"] = ["x86", "arm64"]
    
    dummy = dummy_response(200, {"message": "Successfully uploaded the model card", "model_card_id": "dummy_id"})
    monkeypatch.setattr(requests, "post", lambda url, json: dummy)
    response = requests.post(f"{BASE_URL}/modelcard", json=data)
    assert response.status_code == 200
    assert "Successfully uploaded the model card" in response.json().get("message", "")


def test_upload_model_card_missing_inference_labels(monkeypatch):
    data = load_json("tensorflow_titanic_MC.json")
    dummy = dummy_response(200, {"message": "Successfully uploaded the model card", "model_card_id": "dummy_id"})
    monkeypatch.setattr(requests, "post", lambda url, json: dummy)
    response = requests.post(f"{BASE_URL}/modelcard", json=data)
    assert response.status_code == 200
    assert "Successfully uploaded the model card" in response.json().get("message", "")


def test_register_device_success(client, monkeypatch):
    """Test successful device registration"""
    device_data = {
        "device_id": "test-device-001",
        "device_type": "jetson-nano",
        "location": "test-lab",
        "platform": "x86_64"
    }
    
    # Mock the database operations
    monkeypatch.setattr("legacy.ingester.neo4j_ingester.MCIngester.check_device_exists", lambda self, device_id: False)
    monkeypatch.setattr("legacy.ingester.neo4j_ingester.MCIngester.add_device", lambda self, device: None)
    
    response = client.post("/device", json=device_data)
    assert response.status_code == 201
    data = response.get_json()
    assert data.get("message") == "Device registered successfully"


def test_register_device_missing_device_id(client):
    """Test device registration with missing device_id"""
    device_data = {
        "device_type": "jetson-nano",
        "location": "test-lab"
    }
    
    response = client.post("/device", json=device_data)
    assert response.status_code == 400
    data = response.get_json()
    assert "device_id is required" in data.get("error", "")


def test_register_device_duplicate_id(client, monkeypatch):
    """Test device registration with duplicate device_id"""
    device_data = {
        "device_id": "test-device-001",
        "device_type": "jetson-nano"
    }
    
    # Mock that device already exists
    monkeypatch.setattr("legacy.ingester.neo4j_ingester.MCIngester.check_device_exists", lambda self, device_id: True)
    
    response = client.post("/device", json=device_data)
    assert response.status_code == 409
    data = response.get_json()
    assert "Device with this ID already exists" in data.get("error", "")


def test_register_user_success(client, monkeypatch):
    """Test successful user registration"""
    user_data = {
        "user_id": "test-user-001",
        "email": "test@example.com",
        "full_name": "Test User",
        "organization": "Test University",
        "orcid": "0000-0000-0000-0000"
    }
    
    # Mock the database operations
    monkeypatch.setattr("legacy.ingester.neo4j_ingester.MCIngester.check_user_exists", lambda self, user_id: False)
    monkeypatch.setattr("legacy.ingester.neo4j_ingester.MCIngester.add_user", lambda self, user: None)
    
    response = client.post("/user", json=user_data)
    assert response.status_code == 201
    data = response.get_json()
    assert data.get("message") == "User registered successfully"


def test_register_user_missing_user_id(client):
    """Test user registration with missing user_id"""
    user_data = {
        "email": "test@example.com",
        "full_name": "Test User"
    }
    
    response = client.post("/user", json=user_data)
    assert response.status_code == 400
    data = response.get_json()
    assert "user_id is required" in data.get("error", "")


def test_register_user_duplicate_id(client, monkeypatch):
    """Test user registration with duplicate user_id"""
    user_data = {
        "user_id": "test-user-001",
        "email": "test@example.com"
    }
    
    # Mock that user already exists
    monkeypatch.setattr("legacy.ingester.neo4j_ingester.MCIngester.check_user_exists", lambda self, user_id: True)
    
    response = client.post("/user", json=user_data)
    assert response.status_code == 409
    data = response.get_json()
    assert "User with this ID already exists" in data.get("error", "")
if __name__ == "__main__":
    pytest.main()
