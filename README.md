# Stone Tier 3 – API + Elasticsearch

API de leitura sobre o Elasticsearch com dois endpoints:

1. **Listagem de transações**  
   Filtros: `client_id`, intervalo de datas (`startDate`–`endDate`), paginação (`page`, `size`)

2. **Totais diários por tipo**  
   Filtros: `client_id`, intervalo de datas (`startDate`–`endDate`)

> **Stack**: FastAPI + Uvicorn, Python 3.11, Elasticsearch 8.x, Docker Compose.

---

## ✔️ Pré-requisitos

- Docker Desktop (ou Docker Engine + Compose)
- Porta **5080** livre (API)
- Portas **9200/9300** livres (Elasticsearch)

---

## 🚀 Subir os serviços

Na raiz do projeto:

```bash
docker compose up -d --build

API: http://localhost:5080

Swagger/OpenAPI: http://localhost:5080/docs

Elasticsearch: http://localhost:9200
