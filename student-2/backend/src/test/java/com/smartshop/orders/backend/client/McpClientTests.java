package com.smartshop.orders.backend.client;

import com.smartshop.orders.backend.dto.OrderIntelligenceModels.FulfilmentRequest;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import java.math.BigDecimal;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.client.ExpectedCount.once;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.content;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

class McpClientTests {

    private MockRestServiceServer server;
    private McpClient client;

    @BeforeEach
    void setUp() {
        RestClient.Builder builder = RestClient.builder().baseUrl("http://localhost:7002");
        server = MockRestServiceServer.bindTo(builder).build();
        client = new McpClient(builder.build(), true);
    }

    @Test
    void sendsGroundedOrderFactsToTheSharedTool() {
        server.expect(once(), requestTo("http://localhost:7002/tools/check_order_fulfilment"))
            .andExpect(content().json("""
                {"order_number":"ORD-100","status":"pending","line_count":2,
                 "total_quantity":3,"order_total":89.90,"inventory_committed":true}
                """))
            .andRespond(withSuccess("""
                {"ok":true,"tool":"check_order_fulfilment","result":{
                  "ready_to_ship":true,"blockers":[],
                  "checked_rules":["order_is_pending"],"summary":"Ready"}}
                """, MediaType.APPLICATION_JSON));

        var response = client.checkOrderFulfilment(new FulfilmentRequest(
            "ORD-100", "pending", 2, 3, new BigDecimal("89.90"), true
        ));

        assertThat(response.result().readyToShip()).isTrue();
        assertThat(response.tool()).isEqualTo("check_order_fulfilment");
        server.verify();
    }
}
