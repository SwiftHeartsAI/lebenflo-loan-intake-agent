import os

# Tests always run offline with no tracing, whatever is in .env.
os.environ["LEBENFLO_MODE"] = "offline"
os.environ["PHOENIX_COLLECTOR_ENDPOINT"] = ""
