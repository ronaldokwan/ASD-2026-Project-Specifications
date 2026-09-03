# Student 2 — Customer Orders

Java/Spring Boot implementation of the SmartShop Customer Orders feature.

## Services

| Service | Local port | Responsibility |
| --- | ---: | --- |
| `frontend` | 3002 | Thymeleaf and HTMX pages |
| `backend` | 8002 | Order business API, product/stock coordination, AI |
| `database-api` | 9002 | SQLite ownership and internal CRUD API |

SQLite is embedded inside `database-api`; port 9002 belongs to the Spring Boot API, not to SQLite. The SQLite file is persisted in the Docker volume `student2-orders-data`.

## Run with Docker

From this directory:

```bash
docker compose up --build
```

Open <http://localhost:3002/orders>.

The AI endpoints try the shared Ollama URL and return a development fallback response when Ollama is unavailable. Product details are loaded from Student 1's catalogue API; if that service is unavailable or the SKU is not found, the order service falls back to the raw SKU. Stock methods still return fixed development values until Student 3's API is ready.

The create and edit forms load real products from Student 1. Every order mutation confirms each SKU again in the backend and stores the catalogue price instead of trusting the submitted `unitPrice`. Unknown SKUs are rejected, and orders are not saved while the catalogue is unavailable.

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
GET    http://localhost:8002/api/orders
GET    http://localhost:8002/api/orders/{id}
POST   http://localhost:8002/api/orders
PUT    http://localhost:8002/api/orders/{id}
PATCH  http://localhost:8002/api/orders/{id}/status
DELETE http://localhost:8002/api/orders/{id}

GET    http://localhost:8002/api/orders/{orderId}/lines
POST   http://localhost:8002/api/orders/{orderId}/lines
PUT    http://localhost:8002/api/orders/{orderId}/lines/{lineId}
DELETE http://localhost:8002/api/orders/{orderId}/lines/{lineId}

POST   http://localhost:8002/api/orders/stock-check
POST   http://localhost:8002/api/orders/{id}/ai/delay-email
POST   http://localhost:8002/api/orders/ai/customer-summary

GET    http://localhost:8002/api/catalog/products
GET    http://localhost:8002/api/catalog/products?sku=SKU-AUD-1001
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
  - Calls `GET /api/products?sku={sku}` on Student 1 and reads the `{ "count": ..., "products": [...] }` response.
  - Configure the base URL with `PRODUCT_API_URL` (team Compose uses `http://student-1-backend:8001`).
- `backend/.../service/StockService.java`
  - `StockCheckResult checkStock(List<StockItemRequest> items)`
  - `StockUpdateResult deductStock(String orderNumber, List<StockItemRequest> items)`

The stock integration is isolated behind these methods, so replacing its fixed return values does not require changes to controllers or order persistence.
