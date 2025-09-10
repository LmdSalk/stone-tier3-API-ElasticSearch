# api/app/main.py
from fastapi import FastAPI, Query, HTTPException
from pydantic import BaseModel, ValidationError
from typing import List, Dict
from datetime import datetime
from dateutil.parser import isoparse
import os

from elasticsearch import Elasticsearch

# --- APP precisa existir antes dos decoradores
app = FastAPI(title="StoneSearch.Api", version="1.0.0")

# -----------------------------
# Configuração do Elasticsearch
# -----------------------------
ES_HOST = os.getenv("ES_HOST", "http://elasticsearch:9200")
ES_INDEX = os.getenv("ES_INDEX", "transactions")


def get_es() -> Elasticsearch:
    return Elasticsearch(hosts=[ES_HOST])


def parse_iso(s: str) -> datetime:
    try:
        return isoparse(s)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Data inválida: {s} ({e})")


def _parse_created_at(value):
    """
    Aceita string ISO, epoch (ms ou s) ou datetime;
    retorna datetime (UTC) ou None se não der pra parsear.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        # heurística para epoch ms
        if value > 10_000_000_000:
            return datetime.utcfromtimestamp(value / 1000.0)
        return datetime.utcfromtimestamp(value)
    if isinstance(value, str):
        try:
            return isoparse(value)
        except Exception:
            return None
    return None


# -----------------------------
# Schemas Pydantic (Response)
# -----------------------------
class Transaction(BaseModel):
    id: str
    type: str
    created_at: datetime
    client_id: str
    payer_id: str
    amount: float


class TransactionSearchItem(BaseModel):
    id: str
    score: float
    source: Transaction


class TransactionSearchResponse(BaseModel):
    total: int
    page: int
    size: int
    items: List[TransactionSearchItem]


class DailyTotalsBucket(BaseModel):
    date: datetime
    totalsByType: Dict[str, float]
    totalAllTypes: float


class DailyTotalsResponse(BaseModel):
    clientId: str
    startDate: datetime
    endDate: datetime
    buckets: List[DailyTotalsBucket] = []


# -----------------------------
# Endpoint: /api/transactions/search
# -----------------------------
@app.get(
    "/api/transactions/search",
    response_model=TransactionSearchResponse,
    tags=["transactions"],
)
def search_transactions(
    client_id: str = Query(..., description="ID do cliente"),
    startDate: str = Query(..., description="Início do intervalo (ISO 8601)"),
    endDate: str = Query(..., description="Fim do intervalo (ISO 8601)"),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
):
    start = parse_iso(startDate)
    end = parse_iso(endDate)

    es = get_es()

    from_ = (page - 1) * size
    query = {
        "bool": {
            "filter": [
                {"term": {"client_id": client_id}},
                {"range": {"created_at": {"gte": start.isoformat(), "lte": end.isoformat()}}},
            ]
        }
    }

    # Se houver erro de mapping de created_at para sort, comente a sort abaixo.
    sort = [{"created_at": {"order": "desc"}}]

    try:
        resp = es.search(index=ES_INDEX, from_=from_, size=size, query=query, sort=sort)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Elasticsearch error: {e}")

    hits = resp.get("hits", {})
    total = hits.get("total", {}).get("value", 0)

    items: List[TransactionSearchItem] = []
    for h in hits.get("hits", []):
        src = h.get("_source", {}) or {}

        tx_id = str(src.get("id") or h.get("_id", ""))
        tx_type = str(src.get("type", ""))
        tx_client = str(src.get("client_id", ""))
        tx_payer = str(src.get("payer_id", ""))
        tx_amount_raw = src.get("amount", 0.0)

        try:
            tx_amount = float(tx_amount_raw)
        except Exception:
            tx_amount = 0.0

        tx_created = _parse_created_at(src.get("created_at"))
        if tx_created is None:
            tx_created = datetime.utcfromtimestamp(0)

        try:
            tx = Transaction(
                id=tx_id,
                type=tx_type,
                created_at=tx_created,
                client_id=tx_client,
                payer_id=tx_payer,
                amount=tx_amount,
            )
        except ValidationError:
            # Se o doc não obedece o schema, ignora este item
            continue

        items.append(
            TransactionSearchItem(
                id=tx.id,
                score=h.get("_score") or 0.0,
                source=tx,
            )
        )

    return TransactionSearchResponse(total=total, page=page, size=size, items=items)


# -----------------------------
# Endpoint: /api/transactions/stats/daily
# -----------------------------
@app.get(
    "/api/transactions/stats/daily",
    response_model=DailyTotalsResponse,
    tags=["transactions"],
)
def stats_daily(
    client_id: str = Query(..., description="ID do cliente"),
    startDate: str = Query(..., description="Início do intervalo (ISO 8601)"),
    endDate: str = Query(..., description="Fim do intervalo (ISO 8601)"),
):
    start = parse_iso(startDate)
    end = parse_iso(endDate)

    es = get_es()

    query = {
        "bool": {
            "filter": [
                {"term": {"client_id": client_id}},
                {"range": {"created_at": {"gte": start.isoformat(), "lte": end.isoformat()}}},
            ]
        }
    }

    aggs = {
        "per_day": {
            "date_histogram": {
                "field": "created_at",
                "fixed_interval": "1d",
                "min_doc_count": 0,
            },
            "aggs": {
                "by_type": {
                    "terms": {"field": "type", "size": 20},
                    "aggs": {"total_amount": {"sum": {"field": "amount"}}},
                }
            },
        }
    }

    try:
        resp = es.search(index=ES_INDEX, size=0, query=query, aggs=aggs)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Elasticsearch error: {e}")

    result = DailyTotalsResponse(clientId=client_id, startDate=start, endDate=end, buckets=[])

    per_day = resp.get("aggregations", {}).get("per_day", {}).get("buckets", []) or []
    for b in per_day:
        # dia
        day = _parse_created_at(b.get("key_as_string")) or datetime.utcfromtimestamp(0)

        totals_by_type: Dict[str, float] = {}
        total_all = 0.0

        by_type = b.get("by_type", {}).get("buckets", []) or []
        for tb in by_type:
            tkey = str(tb.get("key", ""))
            s = tb.get("total_amount", {})
            val = s.get("value", 0.0) or 0.0
            try:
                val = float(val)
            except Exception:
                val = 0.0
            totals_by_type[tkey] = val
            total_all += val

        result.buckets.append(
            DailyTotalsBucket(date=day, totalsByType=totals_by_type, totalAllTypes=total_all)
        )

    return result
