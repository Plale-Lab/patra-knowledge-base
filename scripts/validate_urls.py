#!/usr/bin/env python3
"""
URL Validation Script for Patra Knowledge Graph

This script validates all model location URLs in the knowledge graph and updates
the is_orphan boolean field on ModelCard nodes based on URL validity.
"""

import os
import sys
import time
import logging
from urllib.parse import urlparse
import requests
from requests.exceptions import RequestException

# Add the project root to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingester.neo4j_ingester import MCIngester

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def validate_url(url, timeout=10):
    """
    Validate if a URL is accessible
    :param url: URL to validate
    :param timeout: Request timeout in seconds
    :return: (is_valid, error_message)
    """
    try:
        # Check if URL format is valid
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return False, "Invalid URL format"
        
        # Make HTTP request
        response = requests.head(url, timeout=timeout, allow_redirects=True)
        
        # Check if status code indicates success
        if response.status_code < 400:
            return True, None
        else:
            return False, f"HTTP {response.status_code}"
            
    except RequestException as e:
        return False, str(e)
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"


def validate_all_model_urls():
    """
    Main function to validate all model URLs and update orphan status
    """
    # Get database connection parameters from environment
    neo4j_uri = os.getenv('NEO4J_URI', 'bolt://localhost:7687')
    neo4j_user = os.getenv('NEO4J_USER', 'neo4j')
    neo4j_password = os.getenv('NEO4J_PWD', 'password')
    
    try:
        # Initialize database connection
        logger.info("Connecting to Neo4j database...")
        mc_ingester = MCIngester(neo4j_uri, neo4j_user, neo4j_password)
        
        # Get all models with location URLs
        logger.info("Retrieving models with location URLs...")
        models = mc_ingester.get_all_models_with_locations()
        
        if not models:
            logger.info("No models with location URLs found.")
            return
        
        logger.info(f"Found {len(models)} models with location URLs. Starting validation...")
        
        valid_count = 0
        orphan_count = 0
        
        # Validate each model URL
        for i, model in enumerate(models, 1):
            model_id = model['model_id']
            name = model.get('name', 'Unknown')
            version = model.get('version', 'Unknown')
            location = model['location']
            
            logger.info(f"[{i}/{len(models)}] Validating {model_id} ({name} v{version})...")
            
            # Validate URL
            is_valid, error_msg = validate_url(location)
            
            # Update orphan status
            is_orphan = not is_valid
            mc_ingester.update_model_card_orphan_status(model_id, is_orphan)
            
            # Log result
            if is_valid:
                logger.info(f"✅ {model_id}: VALID ({location})")
                valid_count += 1
            else:
                logger.warning(f"❌ {model_id}: ORPHAN ({location}) - {error_msg}")
                orphan_count += 1
            
            # Small delay to avoid overwhelming servers
            time.sleep(0.1)
        
        # Summary
        logger.info(f"\nValidation complete!")
        logger.info(f"Summary: {valid_count} valid, {orphan_count} orphan models")
        
    except Exception as e:
        logger.error(f"Error during URL validation: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    validate_all_model_urls()
