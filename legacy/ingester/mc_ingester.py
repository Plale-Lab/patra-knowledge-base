from ..parser.json_mc_parser import parse_json_mc
from .neo4j_ingester import MCIngester
import os
from dotenv import load_dotenv

load_dotenv()


def main():
    # get the env variables
    NEO4J_URI = os.getenv("NEO4J_URI")
    NEO4J_USERNAME = os.getenv("NEO4J_USER")
    NEO4J_PWD = os.getenv("NEO4J_PWD")
    ENABLE_MC_SIMILARITY = os.getenv("ENABLE_MC_SIMILARITY", "False").lower() == "true"

    mc_ingester = MCIngester(NEO4J_URI, NEO4J_USERNAME, NEO4J_PWD, ENABLE_MC_SIMILARITY)

    # model_card = parse_json_mc("../examples/model_cards/foundational_uci.json")
    model_card = parse_json_mc("/Users/swithana/git/d2i/patra-kg/examples/model_cards/synthetic/megadetector-mc.json")
    mc_ingester.add_mc(model_card)


if __name__ == "__main__":
    main()