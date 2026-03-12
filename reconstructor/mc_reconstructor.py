"""Suspended Neo4j reconstructor retained for archival reference only.

This code path is no longer part of the active backend. PostgreSQL under
rest_server/ is the supported runtime and integration surface.
"""

from ingester.database import GraphDB
from typing import Dict, Optional, Any, List
import logging


class MCReconstructor:
    """
    Re-constructs model cards from the Knowledge Graph.
    
    This class provides functionality to retrieve and reconstruct complete model cards
    from a Neo4j knowledge graph, including associated AI models, bias analysis,
    and explainability analysis.
    """

    def __init__(self, uri: str, user: str, password: str) -> None:
        """
        Initialize the MCReconstructor with Neo4j connection parameters.
        
        Args:
            uri: Neo4j database URI
            user: Database username
            password: Database password
        """
        try:
            self.db = GraphDB(uri, user, password)
            logging.info("Successfully connected to the Neo4j database.")
        except Exception as e:
            logging.error(f"Error connecting to the Neo4j database: {str(e)}")
            raise

    def reconstruct(self, model_card_id: str) -> Optional[Dict[str, Any]]:
        """
        Reconstruct a complete model card from the knowledge graph.
        
        Args:
            model_card_id: The external ID of the model card to reconstruct
            
        Returns:
            A dictionary containing the complete model card data, or None if not found
        """
        base_mc = self._retrieve_base_model_card(model_card_id)
        if base_mc is None:
            return None

        self._clean_model_card(base_mc)
        self._attach_ai_model(base_mc, model_card_id)
        self._attach_bias_analysis(base_mc, model_card_id)
        self._attach_xai_analysis(base_mc, model_card_id)
                
        return base_mc
    
    
    

    def _execute_query(self, query: str, result_key: str, metadata: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """
        Execute a query and return result.
        
        Args:
            query: Cypher query to execute
            result_key: Key to extract from query result
            metadata: Query parameters
            
        Returns:
            Result dictionary or None
        """
        return self.get_result_dict(query, result_key, metadata)

    def _retrieve_base_model_card(self, model_card_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve the base model card from the knowledge graph.
        
        Args:
            model_card_id: The external ID of the model card
            
        Returns:
            Model card dictionary or None
        """
        query = 'MATCH (mc:ModelCard {external_id: $mc_id}) RETURN mc'
        base_mc = self._execute_query(query, "mc", {"mc_id": model_card_id})

        if base_mc is None:
            logging.warning(f"Model card '{model_card_id}' not found in knowledge graph")
        
        return base_mc

    def _clean_model_card(self, model_card: Dict[str, Any]) -> None:
        """
        Remove unnecessary data from the model card (e.g., embeddings).
        
        Args:
            model_card: The model card dictionary to clean
        """
        if 'embedding' in model_card:
            del model_card["embedding"]

    def _attach_ai_model(self, model_card: Dict[str, Any], model_card_id: str) -> None:
        """
        Retrieve and attach AI model information to the model card.
        
        Args:
            model_card: The model card dictionary to update
            model_card_id: The model card ID for constructing the AI model ID
        """
        query = 'MATCH (ai:Model {model_id: $ai_model_id}) RETURN ai'
        ai_model = self._execute_query(
            query, "ai", {"ai_model_id": f"{model_card_id}-model"}
        )
        model_card["ai_model"] = ai_model

    def _attach_bias_analysis(self, model_card: Dict[str, Any], model_card_id: str) -> None:
        """
        Retrieve and attach bias analysis information to the model card if available.
        
        Args:
            model_card: The model card dictionary to update
            model_card_id: The model card ID for constructing the bias analysis ID
        """
        query = 'MATCH (ba:BiasAnalysis {external_id: $bias_id}) RETURN ba'
        bias_analysis = self._execute_query(
            query, "ba", {"bias_id": f"{model_card_id}-bias"}
        )
        if bias_analysis is not None:
            model_card["bias_analysis"] = bias_analysis

    def _attach_xai_analysis(self, model_card: Dict[str, Any], model_card_id: str) -> None:
        """
        Retrieve and attach explainability analysis information to the model card if available.
        
        Args:
            model_card: The model card dictionary to update
            model_card_id: The model card ID for constructing the XAI analysis ID
        """
        query = 'MATCH (xai:ExplainabilityAnalysis {external_id: $xai_id}) RETURN xai'
        xai_analysis = self._execute_query(
            query, "xai", {"xai_id": f"{model_card_id}-xai"}
        )
        if xai_analysis is not None:
            model_card["xai_analysis"] = xai_analysis

    def get_result_dict(self, query: str, result_type: str, metadata: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """Execute a Cypher query and extract the result as a dictionary."""
        response = self.db.get_result_query(query, metadata)
        if response is None:
            return None

        node = response[result_type]
        if node is None:
            return None

        return {key: node[key] for key in node.keys()}

    def search_kg(self, query: str) -> List[Dict[str, Any]]:
        """Search the knowledge graph using full-text search."""
        results = self.db.full_text_search(query)
        return [
            {
                "mc_id": r["mc_id"],
                "name": r["name"],
                "version": r["version"],
                "short_description": r["short_description"],
                "score": r["score"]
            }
            for r in results
        ]

    def get_all_mcs(self) -> List[Dict[str, Any]]:
        """Retrieve all model cards from the knowledge graph."""
        model_cards = self.db.get_all_modelcards()
        return [
            {
                "mc_id": r["mc_id"],
                "name": r["name"],
                "version": r["version"],
                "short_description": r["short_description"]
            }
            for r in model_cards
        ]

    def get_model_location(self, model_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve the download location for a specific model."""
        model_info = self.db.get_model_location(model_id)
        if model_info is None:
            logging.warning(f"Model location not found for model ID: {model_id}")
            return None
            
        return {
            "model_id": model_info["model_id"],
            "name": model_info["name"],
            "version": model_info["version"],
            "download_url": model_info["download_url"]
        }

    def get_deployments(self, model_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve deployment information for a specific model."""
        deployment_info = self.db.get_deployments(model_id)
        if deployment_info is None:
            logging.warning(f"No deployments found for model ID: {model_id}")
            return None
        return deployment_info

    def set_model_location(self, model_id: str, location: str) -> None:
        """Update the download location for a specific model."""
        self.db.set_model_location(model_id, location)
        logging.info(f"Updated model location for {model_id}")


    def get_link_headers(self, model_card: Dict[str, Any]) -> Dict[str, str]:
        """
        Generate HTTP Link and Content-Length headers based on model card data.
        
        Creates HTTP Link headers for related resources like author, input data,
        model location, and inference labels based on the model card content.

        Args:
            model_card: The model card data dictionary
            
        Returns:
            A dictionary containing 'Link' and 'Content-Length' headers
        """
        links = []

        # Extract basic model card information
        model_card_id: str = model_card.get('external_id')
        author: str = model_card.get('author')
        input_data_url: str = model_card.get('input_data')

        # Extract AI model information
        ai_model_dict: Dict[str, Any] = model_card.get('ai_model', {})
        model_location_url: Optional[str] = ai_model_dict.get('location')
        inference_labels_url: Optional[str] = ai_model_dict.get('inference_labels')

        # Build citation link
        if model_card_id:
            links.append(f'<{model_card_id}>; rel="cite-as"')

        # Build author link
        if author and isinstance(author, str):
            if author.startswith(('http://', 'https://')):
                links.append(f'<{author}>; rel="author"')
            else:
                links.append(f'<http://tapis.com/{author}>; rel="author"')

        # Build input data link
        if (input_data_url and isinstance(input_data_url, str) and 
            input_data_url.startswith(('http://', 'https://'))):
            links.append(f'<{input_data_url}>; rel="item"; title="input_data"')

        # Build model location link
        if (model_location_url and isinstance(model_location_url, str) and 
            model_location_url.startswith(('http://', 'https://'))):
            links.append(f'<{model_location_url}>; rel="item"; title="model_location"')

        # Build inference labels link
        if (inference_labels_url and isinstance(inference_labels_url, str) and 
            inference_labels_url.startswith(('http://', 'https://'))):
            links.append(f'<{inference_labels_url}>; rel="item"; title="inference_labels"')

        # Assemble headers
        headers = {}
        if links:
            headers['Link'] = ", ".join(links)

        # Set Content-Length for empty body response
        headers['Content-Length'] = '0'

        return headers
