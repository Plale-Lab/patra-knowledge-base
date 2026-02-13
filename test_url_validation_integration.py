#!/usr/bin/env python3
"""
Integration test for URL validation script
This script adds test models with various URLs and then runs the validation
"""

import os
import sys
import time

# Add the project root to the Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from ingester.neo4j_ingester import MCIngester
from ingester.database import GraphDB

def add_test_models():
    """Add test models with various URLs for testing"""
    
    # Get database connection parameters
    neo4j_uri = os.getenv('NEO4J_URI', 'bolt://localhost:7687')
    neo4j_user = os.getenv('NEO4J_USER', 'neo4j')
    neo4j_password = os.getenv('NEO4J_PWD', 'password')
    
    try:
        # Initialize database connection
        print("Connecting to Neo4j database...")
        db = GraphDB(neo4j_uri, neo4j_user, neo4j_password)
        
        # Test URLs - mix of valid and invalid
        test_models = [
            {
                'model_id': 'test-model-valid-1',
                'name': 'Test Valid Model 1',
                'version': '1.0',
                'location': 'https://httpbin.org/status/200'  # Valid URL
            },
            {
                'model_id': 'test-model-valid-2', 
                'name': 'Test Valid Model 2',
                'version': '1.0',
                'location': 'https://www.google.com'  # Valid URL
            },
            {
                'model_id': 'test-model-invalid-1',
                'name': 'Test Invalid Model 1', 
                'version': '1.0',
                'location': 'https://httpbin.org/status/404'  # Invalid URL (404)
            },
            {
                'model_id': 'test-model-invalid-2',
                'name': 'Test Invalid Model 2',
                'version': '1.0', 
                'location': 'invalid-url-format'  # Invalid URL format
            },
            {
                'model_id': 'test-model-invalid-3',
                'name': 'Test Invalid Model 3',
                'version': '1.0',
                'location': 'https://nonexistent-domain-12345.com'  # Non-existent domain
            }
        ]
        
        print(f"Adding {len(test_models)} test models...")
        
        # Add test models
        for model in test_models:
            query = """
                MERGE (m:Model {model_id: $model_id})
                SET m.name = $name, m.version = $version, m.location = $location
            """
            with db.driver.session() as session:
                session.run(query, **model)
            
            # Also add corresponding ModelCard for orphan status
            modelcard_query = """
                MERGE (mc:ModelCard {external_id: $model_id})
                SET mc.name = $name, mc.version = $version
            """
            with db.driver.session() as session:
                session.run(modelcard_query, model_id=model['model_id'], 
                           name=model['name'], version=model['version'])
            
            print(f"✅ Added test model: {model['model_id']}")
        
        print("Test models added successfully!")
        return True
        
    except Exception as e:
        print(f"Error adding test models: {str(e)}")
        return False

def cleanup_test_models():
    """Remove test models after testing"""
    
    neo4j_uri = os.getenv('NEO4J_URI', 'bolt://localhost:7687')
    neo4j_user = os.getenv('NEO4J_USER', 'neo4j')
    neo4j_password = os.getenv('NEO4J_PWD', 'password')
    
    try:
        db = GraphDB(neo4j_uri, neo4j_user, neo4j_password)
        
        # Remove test models
        test_model_ids = [
            'test-model-valid-1', 'test-model-valid-2',
            'test-model-invalid-1', 'test-model-invalid-2', 'test-model-invalid-3'
        ]
        
        for model_id in test_model_ids:
            # Remove Model node
            model_query = "MATCH (m:Model {model_id: $model_id}) DELETE m"
            with db.driver.session() as session:
                session.run(model_query, model_id=model_id)
            
            # Remove ModelCard node
            modelcard_query = "MATCH (mc:ModelCard {external_id: $model_id}) DELETE mc"
            with db.driver.session() as session:
                session.run(modelcard_query, model_id=model_id)
        
        print("Test models cleaned up successfully!")
        
    except Exception as e:
        print(f"Error cleaning up test models: {str(e)}")

def check_orphan_status():
    """Check the orphan status of test models"""
    
    neo4j_uri = os.getenv('NEO4J_URI', 'bolt://localhost:7687')
    neo4j_user = os.getenv('NEO4J_USER', 'neo4j')
    neo4j_password = os.getenv('NEO4J_PWD', 'password')
    
    try:
        db = GraphDB(neo4j_uri, neo4j_user, neo4j_password)
        
        query = """
            MATCH (mc:ModelCard)
            WHERE mc.external_id STARTS WITH 'test-model-'
            RETURN mc.external_id as model_id, mc.name as name, mc.is_orphan as is_orphan
            ORDER BY mc.external_id
        """
        
        with db.driver.session() as session:
            result = session.run(query)
            records = list(result)
        
        print("\n📊 Orphan Status Check:")
        print("=" * 50)
        for record in records:
            status = "ORPHAN" if record['is_orphan'] else "VALID"
            print(f"{record['model_id']}: {status}")
        
        return records
        
    except Exception as e:
        print(f"Error checking orphan status: {str(e)}")
        return []

if __name__ == "__main__":
    print("🧪 URL Validation Integration Test")
    print("=" * 50)
    
    # Step 1: Add test models
    print("\n1️⃣ Adding test models...")
    if not add_test_models():
        print("Failed to add test models. Exiting.")
        sys.exit(1)
    
    # Step 2: Run URL validation
    print("\n2️⃣ Running URL validation...")
    os.system("python scripts/validate_urls.py")
    
    # Step 3: Check results
    print("\n3️⃣ Checking orphan status...")
    check_orphan_status()
    
    # Step 4: Cleanup (optional)
    print("\n4️⃣ Cleaning up test models...")
    cleanup_test_models()
    
    print("\n✅ Integration test completed!")
