import json


def parse_json_mc(file):
    # read the file
    with open(file, 'r') as json_file:
        json_data = json_file.read()

    # parse the model card
    return json.loads(json_data)

