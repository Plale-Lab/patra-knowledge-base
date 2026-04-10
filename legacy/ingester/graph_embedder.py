import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

ENABLE_MC_SIMILARITY = os.getenv("ENABLE_MC_SIMILARITY", "False").lower() == "true"
OPENAI_API_KEY = None

if ENABLE_MC_SIMILARITY:
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
    if not OPENAI_API_KEY:
        raise ValueError("ENABLE_MC_SIMILARITY is set to True, but OPENAI_API_KEY is not set.")

def open_ai_embedding(model_card, client, fields=None):
    if fields is None:
        fields = ['author', 'short_description', 'full_description', 'version', "input_type", "keywords", "category",
                  "input_data"]
    tokenized_text = " ".join(str(model_card[field]) for field in fields if field in model_card)

    response = client.embeddings.create(
        input=tokenized_text,
        model="text-embedding-3-small",
        encoding_format="float",
        dimensions=300
    )

    return response.data[0].embedding

def embed_model_versioning(model_card, fields=None):
    if not ENABLE_MC_SIMILARITY:
        return None

    client = OpenAI(api_key=OPENAI_API_KEY)
    return open_ai_embedding(model_card, client, fields)
