"""Suspended legacy MCP + Neo4j server.

This module is retained for archive/reference compatibility only.
New development and deployments must use the PostgreSQL-backed FastAPI service
under rest_server/.
"""

from mcp.server.fastmcp import FastMCP
import os
import json
import logging
import hashlib
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from ingester.neo4j_ingester import MCIngester
from reconstructor.mc_reconstructor import MCReconstructor

# Environment variables
NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USERNAME = os.getenv("NEO4J_USER")
NEO4J_PWD = os.getenv("NEO4J_PWD")
ENABLE_MC_SIMILARITY = os.getenv("ENABLE_MC_SIMILARITY", "False").lower() == "true"

# Initialize ingester and reconstructor
mc_ingester = MCIngester(NEO4J_URI, NEO4J_USERNAME, NEO4J_PWD, ENABLE_MC_SIMILARITY)
mc_reconstructor = MCReconstructor(NEO4J_URI, NEO4J_USERNAME, NEO4J_PWD)

logging.basicConfig(level=logging.INFO)
logging.warning(
    "Suspended legacy MCP server initialized. Use rest_server/ with PostgreSQL for all new backend work."
)

# Create MCP server
mcp = FastMCP(
    name="Patra MCP Server",
    host="0.0.0.0",
    port=8050,
)


def get_pid(author: str, name: str, version: str) -> str:
    """
    Generate a persistent ID (PID) for a model card based on author, name, and version.
    Uses SHA256 hash to create a deterministic ID.
    """
    combined = f"{author}:{name}:{version}"
    hash_obj = hashlib.sha256(combined.encode())
    hash_hex = hash_obj.hexdigest()[:8]
    return f"{name}-{version}-{hash_hex}"


# ============================================================================
# MCP Resources (read-only by identifier)
# ============================================================================

@mcp.resource("modelcard://{mc_id}")
async def get_modelcard_resource(mc_id: str) -> str:
    """
    Get a model card by its ID as an MCP resource.
    
    Resources are for reading existing entities by identifier.
    This follows proper MCP semantics for data retrieval.
    
    Args:
        mc_id: The model card ID to retrieve
        
    Returns:
        The model card data as JSON string
    """
    model_card = mc_reconstructor.reconstruct(str(mc_id))
    if model_card is None:
        return json.dumps({"error": "Model card not found"})
    return json.dumps(model_card)


@mcp.resource("modelcard://{mc_id}/download_url")
async def get_model_download_url_resource(mc_id: str) -> str:
    """
    Get the download URL for a model as an MCP resource.
    
    Args:
        mc_id: The model card ID
        
    Returns:
        The download URL information as JSON string
    """
    model_location = mc_reconstructor.get_model_location(str(mc_id))
    if model_location is None:
        return json.dumps({"error": "Model could not be found!"})
    return json.dumps(model_location)


@mcp.resource("modelcard://{mc_id}/deployments")
async def get_model_deployments_resource(mc_id: str) -> str:
    """
    Get deployments for a model as an MCP resource.
    
    Args:
        mc_id: The model card ID
        
    Returns:
        The deployments information as JSON string
    """
    deployments = mc_reconstructor.get_deployments(str(mc_id))
    if deployments is None:
        return json.dumps({"error": "Deployments not found!"})
    return json.dumps(deployments)


@mcp.resource("modelcard://{mc_id}/linkset")
async def get_modelcard_linkset_resource(mc_id: str) -> str:
    """
    Get linkset relations for a model card as an MCP resource.
    
    Args:
        mc_id: The model card ID
        
    Returns:
        The linkset information as JSON string
    """
    model_card = mc_reconstructor.reconstruct(str(mc_id))
    if not model_card:
        return json.dumps({"error": f"Model card with ID '{mc_id}' could not be found!"})
    link_headers = mc_reconstructor.get_link_headers(model_card)
    return json.dumps(link_headers)


# ============================================================================
# MCP Tools (operations and state modifications)
# ============================================================================

@mcp.tool()
async def upload_modelcard(model_card: Dict[str, Any]) -> Dict[str, Any]:
    """
    Upload model card to the Patra Knowledge Graph.
    
    Args:
        model_card: Model card data as dictionary
        
    Returns:
        Dictionary with message and model_card_id
    """
    exists, base_mc_id = mc_ingester.add_mc(model_card)
    if exists:
        return {"message": "Model card already exists", "model_card_id": base_mc_id}
    return {"message": "Successfully uploaded the model card", "model_card_id": base_mc_id}


@mcp.tool()
async def update_modelcard(mc_id: str, model_card: Dict[str, Any]) -> Dict[str, Any]:
    """
    Update an existing model card in the Patra Knowledge Graph.
    
    Args:
        mc_id: The model card ID to update
        model_card: Updated model card data as dictionary
        
    Returns:
        Dictionary with message and model_card_id
    """
    # Ensure the model_card has the correct ID
    model_card['id'] = mc_id
    base_mc_id = mc_ingester.update_mc(model_card)
    if base_mc_id:
        return {"message": "Successfully updated the model card", "model_card_id": base_mc_id}
    return {"message": "Model card not found", "model_card_id": base_mc_id}


@mcp.tool()
async def upload_datasheet(datasheet: Dict[str, Any]) -> Dict[str, Any]:
    """
    Upload datasheet to the Patra Knowledge Graph.
    
    Args:
        datasheet: Datasheet data as dictionary
        
    Returns:
        Dictionary with success message
    """
    mc_ingester.add_datasheet(datasheet)
    return {"message": "Successfully uploaded the datasheet"}


@mcp.tool()
async def update_model_location(mc_id: str, location: str) -> Dict[str, Any]:
    """
    Update the model location URL.
    
    Args:
        mc_id: The model card ID
        location: The new location URL
        
    Returns:
        Dictionary with success message or error
    """
    # Validate URL
    parsed_url = urlparse(location)
    if not all([parsed_url.scheme, parsed_url.netloc]):
        return {"error": "Location must be a valid URL"}
    
    mc_reconstructor.set_model_location(mc_id, location)
    return {"message": "Model location updated successfully"}


@mcp.tool()
async def generate_pid(author: str, name: str, version: str) -> Dict[str, Any]:
    """
    Generate a persistent model ID (PID) for author, name, and version.
    
    Args:
        author: The author of the model
        name: The name of the model
        version: The version of the model
        
    Returns:
        Dictionary with pid, or error if missing parameters or PID already exists
    """
    if not all([author, name, version]):
        logging.error("Missing one or more required parameters: author, name, version")
        return {"error": "Author, name, and version are required"}
    
    pid = get_pid(author, name, version)
    if pid is None:
        logging.error("PID generation failed. Could not generate a unique identifier.")
        return {"error": "PID could not be generated. Please try again."}
    
    if mc_ingester.check_id_exists(pid):
        logging.warning(f"Model ID '{pid}' already exists.")
        return {"pid": pid}  # Return 409 equivalent - PID exists
    
    logging.info(f"Model ID successfully generated: {pid}")
    return {"pid": pid}


@mcp.tool()
async def register_device(device: Dict[str, Any]) -> Dict[str, Any]:
    """
    Register a new edge device for deployment tracking.
    
    Args:
        device: Device information dictionary (must include device_id)
        
    Returns:
        Dictionary with success message or error
    """
    if not device or 'device_id' not in device:
        logging.error("Missing device_id in request")
        return {"error": "device_id is required"}
    
    if mc_ingester.check_device_exists(device['device_id']):
        logging.warning(f"Device with ID '{device['device_id']}' already exists")
        return {"error": "Device with this ID already exists"}
    
    try:
        mc_ingester.add_device(device)
        logging.info(f"Device '{device['device_id']}' registered successfully")
        return {"message": "Device registered successfully"}
    except Exception as e:
        logging.error(f"Failed to register device: {str(e)}")
        return {"error": f"Failed to register device: {str(e)}"}


@mcp.tool()
async def register_user(user: Dict[str, Any]) -> Dict[str, Any]:
    """
    Register a new user for experiment tracking and model submissions.
    
    Args:
        user: User information dictionary (must include user_id)
        
    Returns:
        Dictionary with success message or error
    """
    if not user or 'user_id' not in user:
        logging.error("Missing user_id in request")
        return {"error": "user_id is required"}
    
    if mc_ingester.check_user_exists(user['user_id']):
        logging.warning(f"User with ID '{user['user_id']}' already exists")
        return {"error": "User with this ID already exists"}
    
    try:
        mc_ingester.add_user(user)
        logging.info(f"User '{user['user_id']}' registered successfully")
        return {"message": "User registered successfully"}
    except Exception as e:
        logging.error(f"Failed to register user: {str(e)}")
        return {"error": f"Failed to register user: {str(e)}"}


@mcp.tool()
async def create_edge(source_node_id: str, target_node_id: str) -> Dict[str, Any]:
    """
    Create an edge/relationship between two nodes in the Neo4j graph.
    The relationship type is automatically determined based on the node labels and VALID_LINK_CONSTRAINTS.
    
    Args:
        source_node_id: Neo4j elementId of the source node
        target_node_id: Neo4j elementId of the target node
        
    Returns:
        Dictionary with success status, relationship type, and node information
    """
    # VALID_LINK_CONSTRAINTS mapping
    VALID_LINK_CONSTRAINTS = {
        'ModelCard': ['Datasheet', 'ModelRequirements', 'BiasAnalysis', 'ExplainabilityAnalysis', 'Model'],
        'Model': ['Deployment', 'Experiment'],
        'Server': ['Deployment'],
        'Deployment': ['Experiment', 'Device'],
        'Experiment': ['RawImage', 'User', 'Device', 'Model'],
        'Datasheet': ['ModelCard'],
        'ModelRequirements': ['ModelCard'],
        'BiasAnalysis': ['ModelCard'],
        'ExplainabilityAnalysis': ['ModelCard'],
        'User': ['Experiment'],
        'RawImage': ['Experiment'],
        'Device': ['Deployment', 'Experiment']
    }
    
    # Mapping from (source_label, target_label) to relationship type
    RELATIONSHIP_TYPE_MAP = {
        ('ModelCard', 'Model'): 'USED',
        ('ModelCard', 'Datasheet'): 'TRAINED_ON',
        ('ModelCard', 'ModelRequirements'): 'REQUIREMENTS',
        ('ModelCard', 'BiasAnalysis'): 'BIAS_ANALYSIS',
        ('ModelCard', 'ExplainabilityAnalysis'): 'XAI_ANALYSIS',
        ('Model', 'Deployment'): 'hasDeployment',
        ('Model', 'Experiment'): 'used',
        ('Server', 'Deployment'): 'hosts',
        ('Deployment', 'Experiment'): 'deploymentInfo',
        ('Deployment', 'Device'): 'deployedIn',
        ('Experiment', 'RawImage'): 'uses',
        ('Experiment', 'User'): 'submittedBy',
        ('Experiment', 'Device'): 'runsOn',
        ('Experiment', 'Model'): 'uses',
        ('User', 'Experiment'): 'submittedBy',
        ('RawImage', 'Experiment'): 'usedIn',
        ('Device', 'Deployment'): 'hosts',
        ('Device', 'Experiment'): 'runsOn'
    }
    
    try:
        from neo4j import AsyncGraphDatabase
        
        driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PWD))
        async with driver.session() as session:
            # Get node labels
            query = """
            MATCH (a), (b)
            WHERE elementId(a) = $source_id AND elementId(b) = $target_id
            RETURN labels(a) as source_labels, labels(b) as target_labels
            """
            result = await session.run(query, source_id=source_node_id, target_id=target_node_id)
            record = await result.single()
            
            if not record:
                await driver.close()
                return {"success": False, "error": "One or both nodes not found"}
            
            source_labels = record["source_labels"]
            target_labels = record["target_labels"]
            
            if not source_labels or not target_labels:
                await driver.close()
                return {"success": False, "error": "Nodes have no labels"}
            
            source_label = source_labels[0]
            target_label = target_labels[0]
            
            # Determine relationship type
            relationship_type = RELATIONSHIP_TYPE_MAP.get((source_label, target_label))
            
            if not relationship_type:
                # Check if relationship is valid according to constraints
                if target_label not in VALID_LINK_CONSTRAINTS.get(source_label, []):
                    await driver.close()
                    return {
                        "success": False,
                        "error": f"No valid relationship type between {source_label} and {target_label}",
                        "source_label": source_label,
                        "target_label": target_label
                    }
                # Default relationship type if not in map
                relationship_type = "RELATED_TO"
            
            # Create the edge
            create_query = f"""
            MATCH (a), (b)
            WHERE elementId(a) = $source_id AND elementId(b) = $target_id
            CREATE (a)-[r:{relationship_type}]->(b)
            RETURN r, type(r) as rel_type
            """
            create_result = await session.run(create_query, source_id=source_node_id, target_id=target_node_id)
            created = await create_result.single()
            
            await driver.close()
            
            if created:
                return {
                    "success": True,
                    "message": "Edge created successfully",
                    "relationship_type": relationship_type,
                    "source_node_id": source_node_id,
                    "target_node_id": target_node_id,
                    "source_label": source_label,
                    "target_label": target_label
                }
            else:
                return {"success": False, "error": "Failed to create edge"}
    except Exception as e:
        logging.error(f"Error creating edge: {str(e)}")
        return {"success": False, "error": str(e)}


@mcp.tool()
async def search_modelcards(query: str) -> Dict[str, Any]:
    """
    Full text search for model cards.
    
    Args:
        query: Search query string
        
    Returns:
        Dictionary with search results or error
    """
    if not query:
        return {"error": "Query (q) is required"}
    
    results = mc_reconstructor.search_kg(query)
    return {"results": results}


@mcp.tool()
async def list_modelcards() -> Dict[str, Any]:
    """
    Lists all the models in Patra KG.
    
    Returns:
        Dictionary with all model cards
    """
    model_card_dict = mc_reconstructor.get_all_mcs()
    return model_card_dict


if __name__ == "__main__":
    mcp.run(transport="sse")

