package com.smartshop.orders.backend.client;

import com.smartshop.orders.backend.dto.OrderIntelligenceModels.FulfilmentRequest;
import io.modelcontextprotocol.spec.McpSchema.CallToolRequest;
import io.modelcontextprotocol.spec.McpSchema.CallToolResult;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.web.server.ResponseStatusException;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class McpClientTests {

    @Test
    void callsTheRegisteredMcpToolWithGroundedOrderFacts() {
        AtomicReference<CallToolRequest> captured = new AtomicReference<>();
        McpClient client = new McpClient(request -> {
            captured.set(request);
            return CallToolResult.builder()
                .content(List.of())
                .isError(false)
                .structuredContent(Map.of(
                    "ready_to_ship", true,
                    "blockers", List.of(),
                    "checked_rules", List.of("order_is_pending"),
                    "summary", "Ready"
                ))
                .build();
        }, true);

        var response = client.checkOrderFulfilment(new FulfilmentRequest(
            "ORD-100", "pending", 2, 3, new BigDecimal("89.90"), true
        ));

        assertThat(captured.get().name()).isEqualTo("check_order_fulfilment");
        assertThat(captured.get().arguments()).containsEntry("order_number", "ORD-100")
            .containsEntry("status", "pending")
            .containsEntry("line_count", 2)
            .containsEntry("total_quantity", 3)
            .containsEntry("order_total", new BigDecimal("89.90"))
            .containsEntry("inventory_committed", true);
        assertThat(response.ok()).isTrue();
        assertThat(response.result().readyToShip()).isTrue();
        assertThat(response.tool()).isEqualTo("check_order_fulfilment");
    }

    @Test
    void rejectsAnMcpToolError() {
        McpClient client = new McpClient(request -> CallToolResult.builder()
            .addTextContent("order payload rejected")
            .isError(true)
            .build(), true);

        assertThatThrownBy(() -> client.checkOrderFulfilment(new FulfilmentRequest(
            "ORD-100", "pending", 2, 3, new BigDecimal("89.90"), true
        )))
            .isInstanceOf(ResponseStatusException.class)
            .hasMessageContaining("order payload rejected");
    }

    @Test
    @EnabledIfEnvironmentVariable(named = "RUN_MCP_INTEGRATION_TEST", matches = "true")
    void callsTheLiveStreamableHttpEndpoint() {
        McpClient client = new McpClient("http://localhost:7002", true, 15);

        var response = client.checkOrderFulfilment(new FulfilmentRequest(
            "ORD-LIVE-100", "pending", 1, 2, new BigDecimal("59.90"), true
        ));

        assertThat(response.ok()).isTrue();
        assertThat(response.tool()).isEqualTo("check_order_fulfilment");
        assertThat(response.result().readyToShip()).isTrue();
    }
}
