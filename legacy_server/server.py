"""Suspended legacy Flask + Neo4j server.

This module is retained for archive/reference compatibility only.
New development and deployments must use the PostgreSQL-backed FastAPI service
under rest_server/.
"""

import os
import logging
from urllib.parse import urlparse

from flask import Flask, request, jsonify, Response
from flask_restx import Api, Resource

from ingester.neo4j_ingester import MCIngester
from reconstructor.mc_reconstructor import MCReconstructor

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USERNAME = os.getenv("NEO4J_USER")
NEO4J_PWD = os.getenv("NEO4J_PWD")

ENABLE_MC_SIMILARITY = os.getenv("ENABLE_MC_SIMILARITY", "False").lower() == "true"

mc_ingester = MCIngester(NEO4J_URI, NEO4J_USERNAME, NEO4J_PWD, ENABLE_MC_SIMILARITY)
mc_reconstructor = MCReconstructor(NEO4J_URI, NEO4J_USERNAME, NEO4J_PWD)

logging.basicConfig(level=logging.INFO)
logging.warning(
    "Suspended legacy server initialized. Use rest_server/ with PostgreSQL for all new backend work."
)
app = Flask(__name__)
api = Api(app, version='1.0', title='Patra API',
          description='API to interact with Patra Knowledge Graph',
          doc='/swagger')


@app.route('/')
def home():
    return "Welcome to the Patra Knowledge Base", 200


@api.route('/modelcard')
class ModelCard(Resource):
    def post(self):
        """
        Upload model card to the Patra Knowledge Graph.
        Expects a JSON payload.
        """
        data = request.get_json()
        exists, base_mc_id = mc_ingester.add_mc(data)
        if exists:
            return {"message": "Model card already exists", "model_card_id": base_mc_id}, 200
        return {"message": "Successfully uploaded the model card", "model_card_id": base_mc_id}, 200


@api.route('/modelcard/<string:mc_id>')
class ModelCardDetail(Resource):
    def get(self, mc_id):
        model_card = mc_reconstructor.reconstruct(str(mc_id))
        if model_card is None:
            return {"error": "Model card could not be found!"}, 400
        return model_card, 200
    def head(self, mc_id):
        model_card = mc_reconstructor.reconstruct(str(mc_id))
        if not model_card:
            error_payload = jsonify({"error": f"Model card with ID '{mc_id}' could not be found!"})
            return Response(response=error_payload.get_data(as_text=True), status=404, mimetype='application/json')
        generated_headers = mc_reconstructor.get_link_headers(model_card)
        response = Response(response=None,status=200,mimetype='text/plain')
        response.headers.update(generated_headers)
        return response
    def put(self, mc_id):
        data = request.get_json()
        base_mc_id = mc_ingester.update_mc(data)
        if base_mc_id:
            return {"message": "Successfully updated the model card", "model_card_id": base_mc_id}, 200
        return {"message": "Model card not found", "model_card_id": base_mc_id}, 200


@api.route('/datasheet')
class Datasheet(Resource):
    def post(self):
        """
        Upload datasheet to the Patra Knowledge Graph.
        Expects a JSON payload.
        """
        datasheet_data = request.get_json()
        mc_ingester.add_datasheet(datasheet_data)
        return {"message": "Successfully uploaded the datasheet"}, 200


@api.route('/modelcards/search')
class SearchModelCards(Resource):
    def get(self):
        """
        Full text search for model cards.
        """
        query = request.args.get('q')
        if not query:
            return {"error": "Query (q) is required"}, 400
        results = mc_reconstructor.search_kg(query)
        return results, 200




@api.route('/modelcard/<string:mc_id>/download_url')
class ModelDownloadURL(Resource):
    def get(self, mc_id):
        """
        Download url for a given model id.
        """
        model = mc_reconstructor.get_model_location(str(mc_id))
        if model is None:
            return {"error": "Model could not be found!"}, 400
        return model, 200


@api.route('/modelcards')
class ListModelCards(Resource):
    def get(self):
        """
        Lists all the models in Patra KG.
        """
        model_card_dict = mc_reconstructor.get_all_mcs()
        return model_card_dict, 200


@api.route('/modelcard/<string:mc_id>/deployments')
class ModelDeployments(Resource):
    def get(self, mc_id):
        """
        Get all deployments for a given model ID.
        """
        deployments = mc_reconstructor.get_deployments(mc_id)
        if deployments is None:
            return {"error": "Deployments not found!"}, 400
        return deployments, 200


@api.route('/modelcard/<string:mc_id>/location')
class UpdateModelLocation(Resource):
    def put(self, mc_id):
        """
        Update the model location.
        Expects a JSON payload.
        """
        data = request.get_json()
        if data is None:
            return {"error": "Invalid JSON payload"}, 400
        location = data.get('location')
        if not location:
            return {"error": "Location is required"}, 400
        parsed_url = urlparse(location)
        if not all([parsed_url.scheme, parsed_url.netloc]):
            return {"error": "Location must be a valid URL"}, 400
        mc_reconstructor.set_model_location(mc_id, location)
        return {"message": "Model location updated successfully"}, 200


@api.route('/modelcard/id')
class GeneratePID(Resource):
    def post(self):
        """
        Generates a model_id for a given author, name, and version.
        Returns:
            201: New PID for that combination
            409: PID already exists; user must update version
            400: Missing parameters
        """
        data = request.get_json()
        author = data.get('author')
        name = data.get('name')
        version = data.get('version')
        if not all([author, name, version]):
            logging.error("Missing one or more required parameters: author, name, version")
            return {"error": "Author, name, and version are required"}, 400
        pid = mc_ingester.get_pid(author, name, version)
        if pid is None:
            logging.error("PID generation failed. Could not generate a unique identifier.")
            return {"error": "PID could not be generated. Please try again."}, 500
        if mc_ingester.check_id_exists(pid):
            logging.warning(f"Model ID '{pid}' already exists.")
            return {"pid": pid}, 409
        logging.info(f"Model ID successfully generated: {pid}")
        return {"pid": pid}, 201


@api.route('/modelcard/<string:mc_id>/huggingface_credentials')
class HFcredentials(Resource):
    def get(self, mc_id):
        """
        Retrieves Hugging Face credentials.
        Returns a JSON object with 'username' and 'token'.
        """
        hf_username = os.getenv("HF_HUB_USERNAME")
        hf_token = os.getenv("HF_HUB_TOKEN")
        if not hf_username or not hf_token:
            return {"error": "Hugging Face credentials not set."}, 400
        return {"username": hf_username, "token": hf_token}, 200


@api.route('/modelcard/<string:mc_id>/github_credentials')
class GHcredentials(Resource):
    def get(self, mc_id):
        """
        Retrieves Github credentials.
        Returns a JSON object with 'username' and 'token'.
        """
        gh_username = os.getenv("GH_HUB_USERNAME")
        gh_token = os.getenv("GH_HUB_TOKEN")
        if not gh_username or not gh_token:
            return {"error": "Github credentials not set."}, 400
        return {"username": gh_username, "token": gh_token}, 200


@api.route('/modelcard/<string:mc_id>/linkset')
class ModelCardLinkset(Resource):
    def get(self, mc_id):
        """
        Provides linkset relations for a model card in the HTTP Link header.
        Returns an empty body with link information in the header.
        """
        model_card = mc_reconstructor.reconstruct(str(mc_id))
        if not model_card:
             error_payload = jsonify({"error": f"Model card with ID '{mc_id}' could not be found!"})
             return Response(response=error_payload.get_data(as_text=True), status=404, mimetype='application/json')
        generated_headers = mc_reconstructor.get_link_headers(model_card)
        response = Response(
            response=None,
            status=200,
            mimetype='text/plain'
        )
        response.headers.update(generated_headers)
        return response


@api.route('/device')
class Device(Resource):
    def post(self):
        """
        Register a new edge device for deployment tracking.
        Expects a JSON payload with device information.
        Returns:
            201: Device registered successfully
            400: Missing device_id or invalid data
            409: Device with this ID already exists
        """
        data = request.get_json()
        
        # Validate device_id is required
        if not data or 'device_id' not in data:
            logging.error("Missing device_id in request")
            return {"error": "device_id is required"}, 400
            
        # Check if device already exists
        if mc_ingester.check_device_exists(data['device_id']):
            logging.warning(f"Device with ID '{data['device_id']}' already exists")
            return {"error": "Device with this ID already exists"}, 409
            
        # Register device
        try:
            mc_ingester.add_device(data)
            logging.info(f"Device '{data['device_id']}' registered successfully")
            return {"message": "Device registered successfully"}, 201
        except Exception as e:
            logging.error(f"Failed to register device: {str(e)}")
            return {"error": f"Failed to register device: {str(e)}"}, 500


@api.route('/user')
class User(Resource):
    def post(self):
        """
        Register a new user for experiment tracking and model submissions.
        Expects a JSON payload with user information.
        Returns:
            201: User registered successfully
            400: Missing user_id or invalid data
            409: User with this ID already exists
        """
        data = request.get_json()
        
        # Validate user_id is required
        if not data or 'user_id' not in data:
            logging.error("Missing user_id in request")
            return {"error": "user_id is required"}, 400
            
        # Check if user already exists
        if mc_ingester.check_user_exists(data['user_id']):
            logging.warning(f"User with ID '{data['user_id']}' already exists")
            return {"error": "User with this ID already exists"}, 409
            
        # Register user
        try:
            mc_ingester.add_user(data)
            logging.info(f"User '{data['user_id']}' registered successfully")
            return {"message": "User registered successfully"}, 201
        except Exception as e:
            logging.error(f"Failed to register user: {str(e)}")
            return {"error": f"Failed to register user: {str(e)}"}, 500
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5002)
