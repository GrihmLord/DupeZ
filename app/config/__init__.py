import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "settings.json")

def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

def save_config(config):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=4)
