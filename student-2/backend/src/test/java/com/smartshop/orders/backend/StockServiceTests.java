package com.smartshop.orders.backend;

import com.smartshop.orders.backend.dto.OrderModels.StockItemRequest;
import com.smartshop.orders.backend.service.StockService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.ExpectedCount.once;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.content;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withStatus;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

class StockServiceTests {

    private MockRestServiceServer server;
    private StockService stockService;

    @BeforeEach
    void setUp() {
        RestClient.Builder builder = RestClient.builder();
        server = MockRestServiceServer.bindTo(builder).build();
        stockService = new StockService(builder, "http://student-4-backend:8004");
    }

    @Test
    void confirmsSufficientStockFromStudent4() {
        expectStockLookup("SKU-AUD-1001", 18);

        var result = stockService.checkStock(List.of(new StockItemRequest(" sku-aud-1001 ", 2)));

        assertThat(result.sufficient()).isTrue();
        assertThat(result.message()).isEqualTo("Stock is sufficient");
        server.verify();
    }

    @Test
    void reportsInsufficientStock() {
        expectStockLookup("SKU-AUD-1001", 1);

        var result = stockService.checkStock(List.of(new StockItemRequest("SKU-AUD-1001", 2)));

        assertThat(result.sufficient()).isFalse();
        assertThat(result.message()).contains("available 1, requested 2");
        server.verify();
    }

    @Test
    void reportsMissingStockRecord() {
        server.expect(once(), requestTo("http://student-4-backend:8004/api/stock?sku=UNKNOWN-SKU"))
            .andExpect(method(HttpMethod.GET))
            .andRespond(withSuccess("{\"count\":0,\"stock\":[]}", MediaType.APPLICATION_JSON));

        var result = stockService.checkStock(List.of(new StockItemRequest("UNKNOWN-SKU", 1)));

        assertThat(result.sufficient()).isFalse();
        assertThat(result.message()).contains("No stock record exists for SKU UNKNOWN-SKU");
        server.verify();
    }

    @Test
    void rejectsStockCheckWhenStudent4IsUnavailable() {
        server.expect(once(), requestTo("http://student-4-backend:8004/api/stock?sku=SKU-AUD-1001"))
            .andRespond(withStatus(HttpStatus.SERVICE_UNAVAILABLE));

        assertThatThrownBy(() -> stockService.checkStock(
            List.of(new StockItemRequest("SKU-AUD-1001", 1))))
            .isInstanceOf(ResponseStatusException.class)
            .hasMessageContaining("503 SERVICE_UNAVAILABLE")
            .hasMessageContaining("Stock service is unavailable");
        server.verify();
    }

    @Test
    void deductsStockThroughStudent4UpdateApi() {
        expectStockLookup("SKU-AUD-1001", 18);
        server.expect(once(), requestTo("http://student-4-backend:8004/api/stock/1"))
            .andExpect(method(HttpMethod.PUT))
            .andExpect(content().contentType(MediaType.APPLICATION_JSON))
            .andExpect(content().json("{\"quantity\":16}"))
            .andRespond(withSuccess("{\"id\":1,\"sku\":\"SKU-AUD-1001\",\"quantity\":16}",
                MediaType.APPLICATION_JSON));

        var result = stockService.deductStock(
            "ORD-1001",
            List.of(new StockItemRequest("SKU-AUD-1001", 2))
        );

        assertThat(result.success()).isTrue();
        assertThat(result.message()).contains("ORD-1001");
        server.verify();
    }

    @Test
    void returnsFailureWhenStudent4CannotUpdateStock() {
        expectStockLookup("SKU-AUD-1001", 18);
        server.expect(once(), requestTo("http://student-4-backend:8004/api/stock/1"))
            .andExpect(method(HttpMethod.PUT))
            .andRespond(withStatus(HttpStatus.SERVICE_UNAVAILABLE));

        var result = stockService.deductStock(
            "ORD-1002",
            List.of(new StockItemRequest("SKU-AUD-1001", 2))
        );

        assertThat(result.success()).isFalse();
        assertThat(result.message()).contains("could not update order ORD-1002");
        server.verify();
    }

    private void expectStockLookup(String sku, int quantity) {
        server.expect(once(), requestTo("http://student-4-backend:8004/api/stock?sku=" + sku))
            .andExpect(method(HttpMethod.GET))
            .andRespond(withSuccess("""
                {
                  "count": 1,
                  "stock": [
                    {
                      "id": 1,
                      "sku": "%s",
                      "name": "Inventory item",
                      "quantity": %d,
                      "location": "Shelf A1"
                    }
                  ]
                }
                """.formatted(sku, quantity), MediaType.APPLICATION_JSON));
    }
}
