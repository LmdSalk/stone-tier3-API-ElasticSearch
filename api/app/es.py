import os
from elasticsearch import Elasticsearch

def get_es() -> Elasticsearch:
    # URL do ES (no compose, o hostname costuma ser "elasticsearch")
    url = os.getenv("ELASTIC_URL", "http://elasticsearch:9200")
    # Se seu ES tiver auth, set ELASTIC_USER/ELASTIC_PASS
    user = os.getenv("ELASTIC_USER")
    pwd  = os.getenv("ELASTIC_PASS")

    if user and pwd:
        return Elasticsearch(url, basic_auth=(user, pwd), request_timeout=30)
    return Elasticsearch(url, request_timeout=30)
