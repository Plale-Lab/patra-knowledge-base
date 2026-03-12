import json
import os
import sys
from unittest.mock import MagicMock, patch, AsyncMock
import pytest

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mcp_server.main import (
    get_pid,
    get_modelcard_resource,
    get_model_download_url_resource,
    get_model_deployments_resource,
    get_modelcard_linkset_resource,
    upload_modelcard,
    update_modelcard,
    upload_datasheet,
    update_model_location,
    generate_pid,
    register_device,
    register_user,
    create_edge,
    search_modelcards,
    list_modelcards
)


# ============================================================================
# Test MCP Resources
# ============================================================================

@pytest.mark.asyncio
async def test_get_modelcard_resource_success():
    """Test successful model card resource retrieval."""
    with patch('mcp_server.main.mc_reconstructor') as mock_reconstructor:
        mock_model_card = {
            "external_id": "test-mc-123",
            "name": "Test Model",
            "version": "1.0"
        }
        mock_reconstructor.reconstruct.return_value = mock_model_card
        
        result = await get_modelcard_resource("test-mc-123")
        result_dict = json.loads(result)
        
        assert result_dict == mock_model_card
        mock_reconstructor.reconstruct.assert_called_once_with("test-mc-123")


@pytest.mark.asyncio
async def test_get_modelcard_resource_not_found():
    """Test model card resource when not found."""
    with patch('mcp_server.main.mc_reconstructor') as mock_reconstructor:
        mock_reconstructor.reconstruct.return_value = None
        
        result = await get_modelcard_resource("nonexistent-mc")
        result_dict = json.loads(result)
        
        assert "error" in result_dict
        assert result_dict["error"] == "Model card not found"


@pytest.mark.asyncio
async def test_get_model_download_url_resource_success():
    """Test successful download URL resource retrieval."""
    with patch('mcp_server.main.mc_reconstructor') as mock_reconstructor:
        mock_location = {
            "model_id": "test-mc-123-model",
            "name": "Test Model",
            "version": "1.0",
            "download_url": "https://example.com/model"
        }
        mock_reconstructor.get_model_location.return_value = mock_location
        
        result = await get_model_download_url_resource("test-mc-123")
        result_dict = json.loads(result)
        
        assert result_dict == mock_location


@pytest.mark.asyncio
async def test_get_model_download_url_resource_not_found():
    """Test download URL resource when model not found."""
    with patch('mcp_server.main.mc_reconstructor') as mock_reconstructor:
        mock_reconstructor.get_model_location.return_value = None
        
        result = await get_model_download_url_resource("nonexistent-mc")
        result_dict = json.loads(result)
        
        assert "error" in result_dict
        assert result_dict["error"] == "Model could not be found!"


@pytest.mark.asyncio
async def test_get_model_deployments_resource_success():
    """Test successful deployments resource retrieval."""
    with patch('mcp_server.main.mc_reconstructor') as mock_reconstructor:
        mock_deployments = {
            "deployments": [
                {"deployment_id": "dep1", "location": "edge1"},
                {"deployment_id": "dep2", "location": "edge2"}
            ]
        }
        mock_reconstructor.get_deployments.return_value = mock_deployments
        
        result = await get_model_deployments_resource("test-mc-123")
        result_dict = json.loads(result)
        
        assert result_dict == mock_deployments


@pytest.mark.asyncio
async def test_get_model_deployments_resource_not_found():
    """Test deployments resource when not found."""
    with patch('mcp_server.main.mc_reconstructor') as mock_reconstructor:
        mock_reconstructor.get_deployments.return_value = None
        
        result = await get_model_deployments_resource("nonexistent-mc")
        result_dict = json.loads(result)
        
        assert "error" in result_dict
        assert result_dict["error"] == "Deployments not found!"


@pytest.mark.asyncio
async def test_get_modelcard_linkset_resource_success():
    """Test successful linkset resource retrieval."""
    with patch('mcp_server.main.mc_reconstructor') as mock_reconstructor:
        mock_model_card = {"external_id": "test-mc-123", "name": "Test Model"}
        mock_link_headers = {
            "Link": '<test-mc-123>; rel="cite-as"',
            "Content-Length": "100"
        }
        mock_reconstructor.reconstruct.return_value = mock_model_card
        mock_reconstructor.get_link_headers.return_value = mock_link_headers
        
        result = await get_modelcard_linkset_resource("test-mc-123")
        result_dict = json.loads(result)
        
        assert result_dict == mock_link_headers


@pytest.mark.asyncio
async def test_get_modelcard_linkset_resource_not_found():
    """Test linkset resource when model card not found."""
    with patch('mcp_server.main.mc_reconstructor') as mock_reconstructor:
        mock_reconstructor.reconstruct.return_value = None
        
        result = await get_modelcard_linkset_resource("nonexistent-mc")
        result_dict = json.loads(result)
        
        assert "error" in result_dict
        assert "could not be found" in result_dict["error"]


# ============================================================================
# Test MCP Tools - Model Card Operations
# ============================================================================

@pytest.mark.asyncio
async def test_upload_modelcard_success():
    """Test successful model card upload."""
    with patch('mcp_server.main.mc_ingester') as mock_ingester:
        model_card = {"name": "Test Model", "version": "1.0"}
        mock_ingester.add_mc.return_value = (False, "new-mc-id")
        
        result = await upload_modelcard(model_card)
        
        assert result["message"] == "Successfully uploaded the model card"
        assert result["model_card_id"] == "new-mc-id"
        mock_ingester.add_mc.assert_called_once_with(model_card)


@pytest.mark.asyncio
async def test_upload_modelcard_duplicate():
    """Test model card upload when already exists."""
    with patch('mcp_server.main.mc_ingester') as mock_ingester:
        model_card = {"name": "Test Model", "version": "1.0"}
        mock_ingester.add_mc.return_value = (True, "existing-mc-id")
        
        result = await upload_modelcard(model_card)
        
        assert result["message"] == "Model card already exists"
        assert result["model_card_id"] == "existing-mc-id"


@pytest.mark.asyncio
async def test_update_modelcard_success():
    """Test successful model card update."""
    with patch('mcp_server.main.mc_ingester') as mock_ingester:
        model_card = {"name": "Updated Model", "version": "1.1"}
        mock_ingester.update_mc.return_value = "mc-id-123"
        
        result = await update_modelcard("mc-id-123", model_card)
        
        assert result["message"] == "Successfully updated the model card"
        assert result["model_card_id"] == "mc-id-123"
        # Verify model_card has id set
        assert model_card["id"] == "mc-id-123"


@pytest.mark.asyncio
async def test_update_modelcard_not_found():
    """Test model card update when not found."""
    with patch('mcp_server.main.mc_ingester') as mock_ingester:
        model_card = {"name": "Updated Model", "version": "1.1"}
        mock_ingester.update_mc.return_value = None
        
        result = await update_modelcard("nonexistent-mc", model_card)
        
        assert result["message"] == "Model card not found"
        assert result["model_card_id"] is None


@pytest.mark.asyncio
async def test_upload_datasheet_success():
    """Test successful datasheet upload."""
    with patch('mcp_server.main.mc_ingester') as mock_ingester:
        datasheet = {"name": "Test Dataset", "description": "Test description"}
        
        result = await upload_datasheet(datasheet)
        
        assert result["message"] == "Successfully uploaded the datasheet"
        mock_ingester.add_datasheet.assert_called_once_with(datasheet)


# ============================================================================
# Test MCP Tools - Model Location
# ============================================================================

@pytest.mark.asyncio
async def test_update_model_location_success():
    """Test successful model location update."""
    with patch('mcp_server.main.mc_reconstructor') as mock_reconstructor:
        result = await update_model_location("mc-id-123", "https://example.com/model")
        
        assert result["message"] == "Model location updated successfully"
        mock_reconstructor.set_model_location.assert_called_once_with("mc-id-123", "https://example.com/model")


@pytest.mark.asyncio
async def test_update_model_location_invalid_url():
    """Test model location update with invalid URL."""
    result = await update_model_location("mc-id-123", "not-a-valid-url")
    
    assert "error" in result
    assert "must be a valid URL" in result["error"]


# ============================================================================
# Test MCP Tools - PID Generation
# ============================================================================

@pytest.mark.asyncio
async def test_generate_pid_success():
    """Test successful PID generation."""
    with patch('mcp_server.main.mc_ingester') as mock_ingester:
        mock_ingester.check_id_exists.return_value = False
        
        result = await generate_pid("author1", "model1", "1.0")
        
        assert "pid" in result
        assert result["pid"] is not None
        mock_ingester.check_id_exists.assert_called_once()


@pytest.mark.asyncio
async def test_generate_pid_duplicate():
    """Test PID generation when PID already exists."""
    with patch('mcp_server.main.mc_ingester') as mock_ingester:
        mock_ingester.check_id_exists.return_value = True
        
        result = await generate_pid("author1", "model1", "1.0")
        
        assert "pid" in result
        # Should return PID even if exists (409 equivalent)


@pytest.mark.asyncio
async def test_generate_pid_missing_params():
    """Test PID generation with missing parameters."""
    result = await generate_pid("author1", "", "1.0")
    
    assert "error" in result
    assert "required" in result["error"]


# ============================================================================
# Test MCP Tools - Device Registration
# ============================================================================

@pytest.mark.asyncio
async def test_register_device_success():
    """Test successful device registration."""
    with patch('mcp_server.main.mc_ingester') as mock_ingester:
        device = {
            "device_id": "device-123",
            "device_type": "jetson-nano",
            "location": "lab1"
        }
        mock_ingester.check_device_exists.return_value = False
        
        result = await register_device(device)
        
        assert result["message"] == "Device registered successfully"
        mock_ingester.add_device.assert_called_once_with(device)


@pytest.mark.asyncio
async def test_register_device_missing_device_id():
    """Test device registration with missing device_id."""
    device = {"device_type": "jetson-nano"}
    
    result = await register_device(device)
    
    assert "error" in result
    assert "device_id is required" in result["error"]


@pytest.mark.asyncio
async def test_register_device_duplicate():
    """Test device registration with duplicate device_id."""
    with patch('mcp_server.main.mc_ingester') as mock_ingester:
        device = {"device_id": "device-123"}
        mock_ingester.check_device_exists.return_value = True
        
        result = await register_device(device)
        
        assert "error" in result
        assert "already exists" in result["error"]


# ============================================================================
# Test MCP Tools - User Registration
# ============================================================================

@pytest.mark.asyncio
async def test_register_user_success():
    """Test successful user registration."""
    with patch('mcp_server.main.mc_ingester') as mock_ingester:
        user = {
            "user_id": "user-123",
            "email": "user@example.com",
            "full_name": "Test User"
        }
        mock_ingester.check_user_exists.return_value = False
        
        result = await register_user(user)
        
        assert result["message"] == "User registered successfully"
        mock_ingester.add_user.assert_called_once_with(user)


@pytest.mark.asyncio
async def test_register_user_missing_user_id():
    """Test user registration with missing user_id."""
    user = {"email": "user@example.com"}
    
    result = await register_user(user)
    
    assert "error" in result
    assert "user_id is required" in result["error"]


@pytest.mark.asyncio
async def test_register_user_duplicate():
    """Test user registration with duplicate user_id."""
    with patch('mcp_server.main.mc_ingester') as mock_ingester:
        user = {"user_id": "user-123"}
        mock_ingester.check_user_exists.return_value = True
        
        result = await register_user(user)
        
        assert "error" in result
        assert "already exists" in result["error"]


# ============================================================================
# Test MCP Tools - Edge Creation
# ============================================================================

@pytest.mark.asyncio
async def test_create_edge_success():
    """Test successful edge creation."""
    with patch('neo4j.AsyncGraphDatabase') as mock_driver_class:
        mock_driver = AsyncMock()
        mock_driver_class.driver.return_value = mock_driver

        mock_session = AsyncMock()
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__.return_value = mock_session
        mock_session_cm.__aexit__.return_value = None
        mock_driver.session = MagicMock(return_value=mock_session_cm)

        # Mock the label query result
        mock_record = {
            "source_labels": ["ModelCard"],
            "target_labels": ["Model"],
        }
        mock_result = AsyncMock()
        mock_result.single.return_value = mock_record
        mock_session.run.return_value = mock_result

        # Mock the create query result
        mock_created_record = MagicMock()
        mock_created_result = AsyncMock()
        mock_created_result.single.return_value = mock_created_record
        mock_session.run.side_effect = [mock_result, mock_created_result]

        result = await create_edge("source-id", "target-id")

        assert result["success"] is True
        assert "relationship_type" in result
        mock_driver.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_edge_nodes_not_found():
    """Test edge creation when nodes not found."""
    with patch('neo4j.AsyncGraphDatabase') as mock_driver_class:
        mock_driver = AsyncMock()
        mock_driver_class.driver.return_value = mock_driver

        mock_session = AsyncMock()
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__.return_value = mock_session
        mock_session_cm.__aexit__.return_value = None
        mock_driver.session = MagicMock(return_value=mock_session_cm)

        mock_result = AsyncMock()
        mock_result.single.return_value = None
        mock_session.run.return_value = mock_result

        result = await create_edge("nonexistent-source", "nonexistent-target")

        assert result["success"] is False
        assert "not found" in result["error"]


@pytest.mark.asyncio
async def test_create_edge_invalid_relationship():
    """Test edge creation with invalid relationship."""
    with patch('neo4j.AsyncGraphDatabase') as mock_driver_class:
        mock_driver = AsyncMock()
        mock_driver_class.driver.return_value = mock_driver

        mock_session = AsyncMock()
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__.return_value = mock_session
        mock_session_cm.__aexit__.return_value = None
        mock_driver.session = MagicMock(return_value=mock_session_cm)

        mock_record = {
            "source_labels": ["ModelCard"],
            "target_labels": ["InvalidLabel"],
        }
        mock_result = AsyncMock()
        mock_result.single.return_value = mock_record
        mock_session.run.return_value = mock_result

        result = await create_edge("source-id", "target-id")

        assert result["success"] is False
        assert "No valid relationship" in result["error"]


# ============================================================================
# Test MCP Tools - Search and List
# ============================================================================

@pytest.mark.asyncio
async def test_search_modelcards_success():
    """Test successful model card search."""
    with patch('mcp_server.main.mc_reconstructor') as mock_reconstructor:
        mock_results = [
            {"mc_id": "mc1", "name": "Model 1", "score": 0.9},
            {"mc_id": "mc2", "name": "Model 2", "score": 0.8}
        ]
        mock_reconstructor.search_kg.return_value = mock_results
        
        result = await search_modelcards("test query")
        
        assert "results" in result
        assert result["results"] == mock_results
        mock_reconstructor.search_kg.assert_called_once_with("test query")


@pytest.mark.asyncio
async def test_search_modelcards_missing_query():
    """Test search with missing query."""
    result = await search_modelcards("")
    
    assert "error" in result
    assert "required" in result["error"]


@pytest.mark.asyncio
async def test_list_modelcards_success():
    """Test successful model card listing."""
    with patch('mcp_server.main.mc_reconstructor') as mock_reconstructor:
        mock_results = [
            {"mc_id": "mc1", "name": "Model 1"},
            {"mc_id": "mc2", "name": "Model 2"}
        ]
        mock_reconstructor.get_all_mcs.return_value = mock_results
        
        result = await list_modelcards()
        
        assert result == mock_results
        mock_reconstructor.get_all_mcs.assert_called_once()


# ============================================================================
# Test Helper Functions
# ============================================================================

def test_get_pid():
    """Test PID generation function."""
    pid1 = get_pid("author1", "model1", "1.0")
    pid2 = get_pid("author1", "model1", "1.0")
    
    # Same inputs should produce same PID
    assert pid1 == pid2
    
    # Different inputs should produce different PIDs
    pid3 = get_pid("author2", "model1", "1.0")
    assert pid1 != pid3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

