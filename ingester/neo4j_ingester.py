"""Suspended Neo4j ingester retained for archival reference only.

This code path is no longer part of the active backend. PostgreSQL under
rest_server/ is the supported runtime and integration surface.
"""

import uuid

from ingester.database import GraphDB
from ingester.graph_embedder import embed_model_versioning


class MCIngester:

    def __init__(self, uri, user, password, similarity_support=False):
        self.uri = uri
        self.user = user
        self.password = password
        self.similarity_enabled = similarity_support
        try:
            self.db = GraphDB(self.uri, self.user, self.password)
            print("Connected to the Neo4j database.")
        except Exception as e:
            print("Error connecting to the Neo4j database:", str(e))

    def add_mc(self, model_card):
        """
        Add a model card to the knowledge graph.

        :param model_card: Model card to add.
        :return: Tuple of (exists, model_id) where exists is a boolean indicating if the model card already exists and
        """
        exists, model_id = self.db.check_mc_exists(model_card)
        if exists:
            return exists, model_id

        if 'id' not in model_card:
            model_card['id'] = str(uuid.uuid4())

        if self.similarity_enabled:
            version_embedding = embed_model_versioning(model_card)
            model_card['embedding'] = version_embedding

        self.db.insert_base_mc(model_card, self.similarity_enabled)

        base_mc_id = model_card['id']
        datasheet_id = model_card['input_data']
        self.db.connect_datasheet_mc(datasheet_id, base_mc_id)
        self.db.insert_ai_model(base_mc_id, model_card['ai_model'])

        bias_analysis = model_card["bias_analysis"]
        if bias_analysis is not None:
            bias_id = base_mc_id + "-bias"
            self.db.insert_bias_analysis_metadata(base_mc_id, bias_id, bias_analysis)

        xai_analysis = model_card["xai_analysis"]
        if xai_analysis is not None:
            xai_id = base_mc_id + "-xai"
            self.db.insert_xai_analysis_metadata(base_mc_id, xai_id, xai_analysis)

        if "model_requirements" in model_card:
            model_requirements = model_card["model_requirements"]
            if model_requirements is not None:
                requirements_id = base_mc_id + "-requirements"
                self.db.insert_model_requirements_metadata(base_mc_id, requirements_id, model_requirements)

        foundational_mc_id = model_card['foundational_model']
        if foundational_mc_id:
            self.db.connect_foundational_model(base_mc_id, foundational_mc_id)

        # infer versioning
        if self.similarity_enabled:
            self.db.infer_versioning(model_card)
        return exists, base_mc_id

    def update_mc(self, model_card):
        """
        Update the existing model card.

        :param model_card: Model card to update.
        :return: Model card ID if found, None otherwise.
        """
        base_mc_id = self.db.check_update_mc(model_card)
        if base_mc_id:
            self.db.update_base_mc(base_mc_id, model_card)
            self.db.update_ai_model(base_mc_id, model_card['ai_model'])

            bias_analysis = model_card["bias_analysis"]
            if bias_analysis is not None:
                bias_id = base_mc_id + "-bias"
                self.db.update_bias_analysis_metadata(base_mc_id, bias_id, bias_analysis)

            xai_analysis = model_card["xai_analysis"]
            if xai_analysis is not None:
                xai_id = base_mc_id + "-xai"
                self.db.update_xai_analysis_metadata(base_mc_id, xai_id, xai_analysis)

            model_requirements = model_card["model_requirements"]
            if model_requirements is not None:
                requirements_id = base_mc_id + "-requirements"
                self.db.update_model_requirements_metadata(requirements_id, model_requirements)

        return base_mc_id

    def add_datasheet(self, datasheet):
        self.db.insert_datasheet(datasheet)

    def add_device(self, device):
        self.db.insert_device(device)

    def check_device_exists(self, device_id):
        """
        Check if a device with the given device_id already exists.
        :param device_id: The device ID to check
        :return: True if device exists, False otherwise
        """
        return self.db.check_device_exists(device_id)

    def check_user_exists(self, user_id):
        """
        Check if a user with the given user_id already exists.
        :param user_id: The user ID to check
        :return: True if user exists, False otherwise
        """
        return self.db.check_user_exists(user_id)

    def add_user(self, user):
        """
        Add a user to the knowledge graph.
        :param user: User data dictionary
        """
        self.db.insert_user(user)
    def add_deployment(self, deployment):
        self.db.insert_deployment(deployment)

    def version_perf_test(self, model_card):
        return self.db.versioning_perf_test(model_card)

    def check_id_exists(self, pid):
        return self.db.check_id_exists(pid)
