package com.smartshop.orders.frontend;

import com.smartshop.orders.frontend.client.BackendClient;
import com.smartshop.orders.frontend.dto.FrontendModels.OrderLineRequest;
import com.smartshop.orders.frontend.dto.FrontendModels.OrderRequest;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import java.math.BigDecimal;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.ExpectedCount.once;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withStatus;

class BackendClientTests {

    private MockRestServiceServer server;
    private BackendClient backendClient;

    @BeforeEach
    void setUp() {
        RestClient.Builder builder = RestClient.builder();
        server = MockRestServiceServer.bindTo(builder).build();
        backendClient = new BackendClient(builder, "http://student2-api:8002");
    }

    @Test
    void exposesTheBackendBusinessMessageForTheOrderForm() {
        server.expect(once(), requestTo("http://student2-api:8002/api/orders"))
            .andRespond(withStatus(HttpStatus.CONFLICT).body("""
                {
                  "timestamp": "2026-09-03T00:00:00Z",
                  "status": 409,
                  "error": "Conflict",
                  "message": "Insufficient stock for SKU SKU-AUD-1001 (available 50, requested 1000)"
                }
                """).contentType(MediaType.APPLICATION_JSON));

        OrderRequest request = new OrderRequest(
            "buyer@example.com",
            "pending",
            List.of(new OrderLineRequest(null, "SKU-AUD-1001", 1000, new BigDecimal("199.95")))
        );

        assertThatThrownBy(() -> backendClient.create(request))
            .isInstanceOf(IllegalStateException.class)
            .hasMessage("Insufficient stock for SKU SKU-AUD-1001 (available 50, requested 1000)");
        server.verify();
    }
}
