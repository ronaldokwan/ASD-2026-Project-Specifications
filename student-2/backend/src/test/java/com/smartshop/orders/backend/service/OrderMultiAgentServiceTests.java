package com.smartshop.orders.backend.service;

import tools.jackson.databind.ObjectMapper;
import com.smartshop.orders.backend.client.McpClient;
import com.smartshop.orders.backend.client.MultiAgentClient;
import com.smartshop.orders.backend.dto.MultiAgentModels.ReviewRequest;
import com.smartshop.orders.backend.dto.MultiAgentModels.StartWorkflowRequest;
import com.smartshop.orders.backend.dto.MultiAgentModels.StartWorkflowResponse;
import com.smartshop.orders.backend.dto.MultiAgentModels.WorkflowResponse;
import com.smartshop.orders.backend.dto.OrderIntelligenceModels.FulfilmentResult;
import com.smartshop.orders.backend.dto.OrderIntelligenceModels.McpToolResponse;
import com.smartshop.orders.backend.dto.OrderIntelligenceModels.RagAnswerResponse;
import com.smartshop.orders.backend.dto.OrderIntelligenceModels.RagSource;
import com.smartshop.orders.backend.dto.OrderModels.OrderLineResponse;
import com.smartshop.orders.backend.dto.OrderModels.OrderResponse;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.web.server.ResponseStatusException;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class OrderMultiAgentServiceTests {

    private OrderService orderService;
    private McpClient mcpClient;
    private OrderRagService ragService;
    private MultiAgentClient multiAgentClient;
    private OrderMultiAgentService service;

    @BeforeEach
    void setUp() {
        orderService = mock(OrderService.class);
        mcpClient = mock(McpClient.class);
        ragService = mock(OrderRagService.class);
        multiAgentClient = mock(MultiAgentClient.class);
        service = new OrderMultiAgentService(
            orderService, mcpClient, ragService, multiAgentClient, new ObjectMapper()
        );
        when(orderService.get(42L)).thenReturn(order());
    }

    @Test
    void startsAnOrderWorkflowWithSanitisedMcpAndRagEvidence() {
        when(mcpClient.checkOrderFulfilment(any())).thenReturn(new McpToolResponse(
            true,
            "check_order_fulfilment",
            new FulfilmentResult(true, List.of(), List.of("order_is_pending"), "Ready"),
            null
        ));
        when(ragService.ask(any(), any())).thenReturn(new RagAnswerResponse(
            "ok",
            "The order may be shipped.",
            null,
            "high",
            List.of(new RagSource(
                "orders-shipping-policy-v1", "policy-1", "Pending orders may ship.", Map.of()
            )),
            2,
            10,
            null
        ));
        when(multiAgentClient.start(any())).thenReturn(
            new StartWorkflowResponse("wf-42", "queued", null)
        );

        assertThat(service.start(42L).workflowId()).isEqualTo("wf-42");

        ArgumentCaptor<StartWorkflowRequest> request = ArgumentCaptor.forClass(StartWorkflowRequest.class);
        verify(multiAgentClient).start(request.capture());
        assertThat(request.getValue().subjectRef()).isEqualTo("student-2-order:42");
        assertThat(request.getValue().evidence()).extracting("id")
            .containsExactly("order_facts", "mcp_fulfilment", "shipping_policy");
        assertThat(request.getValue().evidence()).extracting("status")
            .containsExactly("available", "available", "available");
        assertThat(request.getValue().evidence().get(0).content())
            .contains("ORD-R2-0042", "SKU-AUD-1001", "inventory_committed")
            .doesNotContain("buyer@example.com");
        assertThat(request.getValue().request().workerPolicyEvidenceIds())
            .containsExactly("shipping_policy");
        assertThat(request.getValue().request().planContract().constraints())
            .anyMatch(value -> value.contains("must not mutate"));
        verify(ragService).ask(
            any(),
            eq("Under the internal shipping policy, when may an order proceed to shipment?")
        );
    }

    @Test
    void recordsUnavailableDependenciesAsEvidenceInsteadOfInventingResults() {
        when(mcpClient.checkOrderFulfilment(any())).thenThrow(new RuntimeException("MCP offline"));
        when(ragService.ask(any(), any())).thenThrow(new RuntimeException("RAG offline"));
        when(multiAgentClient.start(any())).thenReturn(
            new StartWorkflowResponse("wf-42", "queued", null)
        );

        service.start(42L);

        ArgumentCaptor<StartWorkflowRequest> request = ArgumentCaptor.forClass(StartWorkflowRequest.class);
        verify(multiAgentClient).start(request.capture());
        assertThat(request.getValue().evidence()).extracting("status")
            .containsExactly("available", "unavailable", "unavailable");
    }

    @Test
    void preventsAccessToAWorkflowOwnedByAnotherOrder() {
        when(multiAgentClient.get("wf-other")).thenReturn(workflow("student-2-order:99"));

        assertThatThrownBy(() -> service.get(42L, "wf-other"))
            .isInstanceOf(ResponseStatusException.class)
            .hasMessageContaining("does not belong to this order");
    }

    @Test
    void validatesPartialAcceptanceBeforeCallingTheSharedService() {
        when(multiAgentClient.get("wf-42")).thenReturn(workflow("student-2-order:42"));
        ReviewRequest incomplete = new ReviewRequest(
            "partial_accept", "", List.of(), List.of(), Map.of()
        );

        assertThatThrownBy(() -> service.review(42L, "wf-42", incomplete))
            .isInstanceOf(ResponseStatusException.class)
            .hasMessageContaining("partial acceptance requires");
    }

    private WorkflowResponse workflow(String subjectRef) {
        return new WorkflowResponse(
            "wf-42", subjectRef, "human_review", "human_review",
            Map.of(), Map.of(), Map.of(), null, List.of(), List.of(), 0, 1,
            Map.of(
                "planner_completed", true,
                "worker_completed", true,
                "reviewer_completed", true,
                "human_decision_recorded", false
            ),
            null, null
        );
    }

    private OrderResponse order() {
        LocalDateTime now = LocalDateTime.of(2026, 10, 23, 10, 30);
        return new OrderResponse(
            42L,
            "ORD-R2-0042",
            "buyer@example.com",
            "pending",
            now,
            now,
            List.of(new OrderLineResponse(
                7L,
                "SKU-AUD-1001",
                "Aurora Wireless Headphones",
                2,
                new BigDecimal("99.95"),
                new BigDecimal("199.90")
            )),
            2,
            new BigDecimal("199.90")
        );
    }
}
