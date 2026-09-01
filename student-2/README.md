# Student 2 — Customer Orders

Java/Spring Boot implementation of the SmartShop Customer Orders feature.

## Services

| Service | Local port | Responsibility |
| --- | ---: | --- |
| `frontend` | 5201 | Thymeleaf and HTMX pages |
| `backend` | 5202 | Order business API, product/stock coordination, AI |
| `database-api` | 5203 | SQLite ownership and internal CRUD API |

SQLite is embedded inside `database-api`; port 5203 belongs to the Spring Boot API, not to SQLite. The SQLite file is persisted in the Docker volume `student2-orders-data`.

## Run with Docker

From this directory:

```bash
docker compose up --build
```

Open <http://localhost:5201/orders>.

The AI endpoints try the shared Ollama URL and return a development fallback response when Ollama is unavailable. Product and stock methods currently return fixed development values. Their method bodies can be replaced with Student 1 and Student 3 HTTP calls later.

## Run locally

Use three terminals from the project root:

```bash
mvn -pl database-api spring-boot:run
mvn -pl backend spring-boot:run
mvn -pl frontend spring-boot:run
```

The database service automatically seeds ten orders when its database is empty.

## Build and test

```bash
mvn clean verify
```

## Main APIs

```text
GET    http://localhost:5202/api/orders
GET    http://localhost:5202/api/orders/{id}
POST   http://localhost:5202/api/orders
PUT    http://localhost:5202/api/orders/{id}
PATCH  http://localhost:5202/api/orders/{id}/status
DELETE http://localhost:5202/api/orders/{id}

GET    http://localhost:5202/api/orders/{orderId}/lines
POST   http://localhost:5202/api/orders/{orderId}/lines
PUT    http://localhost:5202/api/orders/{orderId}/lines/{lineId}
DELETE http://localhost:5202/api/orders/{orderId}/lines/{lineId}

POST   http://localhost:5202/api/orders/stock-check
POST   http://localhost:5202/api/orders/{id}/ai/delay-email
POST   http://localhost:5202/api/orders/ai/customer-summary
```

Example create request:

```json
{
  "customerEmail": "customer@example.com",
  "status": "pending",
  "lines": [
    {
      "sku": "SKU-001",
      "quantity": 2,
      "unitPrice": 19.95
    }
  ]
}
```

## Integration replacement points

- `backend/.../service/ProductService.java`
  - `ProductInfo getProductBySku(String sku)`
- `backend/.../service/StockService.java`
  - `StockCheckResult checkStock(List<StockItemRequest> items)`
  - `StockUpdateResult deductStock(String orderNumber, List<StockItemRequest> items)`

The business services call only these methods, so replacing the fixed return values does not require changes to controllers or order persistence.
