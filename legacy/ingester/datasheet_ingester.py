from ..parser.json_mc_parser import parse_json_mc
from .neo4j_ingester import MCIngester
import os
from dotenv import load_dotenv

load_dotenv()


def main():
    NEO4J_URI = os.getenv("NEO4J_URI")
    NEO4J_USERNAME = os.getenv("NEO4J_USER")
    NEO4J_PWD = os.getenv("NEO4J_PWD")
    mc_ingester = MCIngester(NEO4J_URI, NEO4J_USERNAME, NEO4J_PWD)


    datasheet = parse_json_mc("../examples/datasheets/megadetector-input-data.json")

    mc_ingester.add_datasheet(datasheet)

if __name__ == "__main__":
    main()