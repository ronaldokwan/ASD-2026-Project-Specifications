package com.smartshop.orders.backend.service;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.ObjectMapper;
import com.smartshop.orders.backend.client.McpClient;
import com.smartshop.orders.backend.client.MultiAgentClient;
import com.smartshop.orders.backend.dto.MultiAgentModels.Evidence;
import com.smartshop.orders.backend.dto.MultiAgentModels.PlanContract;
import com.smartshop.orders.backend.dto.MultiAgentModels.ReviewRequest;
import com.smartshop.orders.backend.dto.MultiAgentModels.StartWorkflowRequest;
import com.smartshop.orders.backend.dto.MultiAgentModels.StartWorkflowResponse;
import com.smartshop.orders.backend.dto.MultiAgentModels.WorkflowHistoryResponse;
import com.smartshop.orders.backend.dto.MultiAgentModels.WorkflowRequest;
import com.smartshop.orders.backend.dto.MultiAgentModels.WorkflowResponse;
import com.smartshop.orders.backend.dto.OrderIntelligenceModels.FulfilmentRequest;
import com.smartshop.orders.backend.dto.OrderIntelligenceModels.RagAnswerResponse;
import com.smartshop.orders.backend.dto.OrderModels.OrderResponse;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Service
public class OrderMultiAgentService {

    private static final String ORDER_FACTS = "order_facts";
    private static final String MCP_FULFILMENT = "mcp_fulfilment";
    private static final String SHIPPING_POLICY = "shipping_policy";

    private final OrderService orderService;
    private final McpClient mcpClient;
    private final OrderRagService ragService;
    private final MultiAgentClient multiAgentClient;
    private final ObjectMapper objectMapper;

    public OrderMultiAgentService(
        OrderService orderService,
        McpClient mcpClient,
        OrderRagService ragService,
        MultiAgentClient multiAgentClient,
        ObjectMapper objectMapper
    ) {
        this.orderService = orderService;
        this.mcpClient = mcpClient;
        this.ragService = ragService;
        this.multiAgentClient = multiAgentClient;
        this.objectMapper = objectMapper;
    }

    public StartWorkflowResponse start(long orderId) {
        OrderResponse order = orderService.get(orderId);
        List<Evidence> evidence = new ArrayList<>();
        evidence.add(orderEvidence(order));
        evidence.add(mcpEvidence(order));
        evidence.add(policyEvidence(order));

        PlanContract contract = new PlanContract(
            List.of(
                "Confirm the current order status, lines, quantity, total and inventory commitment from order_facts.",
                "Use mcp_fulfilment to determine whether deterministic fulfilment checks passed.",
                "Use shipping_policy for the policy rules supporting the shipment recommendation."
            ),
            List.of(
                "Use only supplied evidence and cite its exact evidence ID.",
                "Do not infer customer data, payment state or inventory beyond the supplied evidence.",
                "The recommendation is informational and must not mutate, ship or otherwise change the order.",
                "If required evidence is unavailable or insufficient, state that a safe recommendation cannot be made."
            )
        );
        WorkflowRequest request = new WorkflowRequest(
            "Review whether this customer order is ready for shipment and provide a grounded recommendation for human review.",
            contract,
            List.of(ORDER_FACTS, MCP_FULFILMENT, SHIPPING_POLICY),
            List.of(ORDER_FACTS, MCP_FULFILMENT, SHIPPING_POLICY),
            List.of(SHIPPING_POLICY)
        );
        return multiAgentClient.start(new StartWorkflowRequest(
            subjectRef(orderId), request, List.copyOf(evidence), 1
        ));
    }

    public WorkflowResponse get(long orderId, String workflowId) {
        orderService.get(orderId);
        return requireOwnership(orderId, multiAgentClient.get(workflowId));
    }

    public WorkflowHistoryResponse history(long orderId) {
        orderService.get(orderId);
        WorkflowHistoryResponse history = multiAgentClient.history(subjectRef(orderId));
        boolean wrongOwner = history.workflows().stream()
            .anyMatch(workflow -> !subjectRef(orderId).equals(workflow.subjectRef()));
        if (wrongOwner) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY,
                "Shared Multi-Agent service returned workflow history for another order");
        }
        return history;
    }

    public WorkflowResponse review(long orderId, String workflowId, ReviewRequest request) {
        orderService.get(orderId);
        requireOwnership(orderId, multiAgentClient.get(workflowId));
        validateReview(request);
        return requireOwnership(orderId, multiAgentClient.review(workflowId, request));
    }

    private Evidence orderEvidence(OrderResponse order) {
        Map<String, Object> facts = new LinkedHashMap<>();
        facts.put("order_number", order.orderNumber());
        facts.put("status", order.status());
        facts.put("line_count", order.lines().size());
        facts.put("total_quantity", order.totalQuantity());
        facts.put("order_total", order.orderTotal());
        facts.put("products", order.lines().stream().map(line -> line.sku()).toList());
        facts.put("inventory_committed", true);
        return new Evidence(
            ORDER_FACTS,
            "student-2-orders-api",
            "available",
            "Authoritative for the current sanitised order facts. Customer identity is deliberately excluded.",
            json(facts)
        );
    }

    private Evidence mcpEvidence(OrderResponse order) {
        try {
            var result = mcpClient.checkOrderFulfilment(new FulfilmentRequest(
                order.orderNumber(), order.status(), order.lines().size(),
                order.totalQuantity(), order.orderTotal(), true
            ));
            return new Evidence(
                MCP_FULFILMENT,
                "shared-mcp-check_order_fulfilment",
                "available",
                "Authoritative deterministic validation of the order fulfilment rules; it does not define shipping policy.",
                json(result)
            );
        } catch (RuntimeException exception) {
            return new Evidence(
                MCP_FULFILMENT,
                "shared-mcp-check_order_fulfilment",
                "unavailable",
                "The deterministic fulfilment check was unavailable and must not be inferred.",
                "MCP fulfilment evidence is unavailable: " + safeMessage(exception)
            );
        }
    }

    private Evidence policyEvidence(OrderResponse order) {
        try {
            RagAnswerResponse response = ragService.ask(
                order,
                "Can this order be shipped, and which shipping policy rules support the decision?"
            );
            boolean policyFound = "ok".equals(response.status())
                && response.sources() != null
                && response.sources().stream().anyMatch(source ->
                    source.docId() != null && source.docId().startsWith("orders-shipping-policy")
                );
            return new Evidence(
                SHIPPING_POLICY,
                "shared-rag-orders-shipping-policy",
                policyFound ? "available" : "insufficient",
                "Authoritative shipping-policy evidence only when the RAG response cites the SmartShop shipping policy.",
                json(response)
            );
        } catch (RuntimeException exception) {
            return new Evidence(
                SHIPPING_POLICY,
                "shared-rag-orders-shipping-policy",
                "unavailable",
                "Shipping-policy evidence could not be retrieved and must not be inferred.",
                "RAG shipping-policy evidence is unavailable: " + safeMessage(exception)
            );
        }
    }

    private WorkflowResponse requireOwnership(long orderId, WorkflowResponse workflow) {
        if (!subjectRef(orderId).equals(workflow.subjectRef())) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND,
                "Multi-Agent workflow does not belong to this order");
        }
        return workflow;
    }

    private void validateReview(ReviewRequest request) {
        String feedback = request.feedback() == null ? "" : request.feedback().trim();
        if ("reject".equals(request.decision()) && feedback.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                "feedback is required when rejecting a recommendation");
        }
        if ("partial_accept".equals(request.decision())) {
            boolean missingCorrection = request.correctedOutput() == null
                || blank(request.correctedOutput().get("recommendation"))
                || blank(request.correctedOutput().get("rationale"));
            if (feedback.isEmpty() || missingCorrection
                || request.acceptedFields() == null || request.acceptedFields().isEmpty()
                || request.unresolvedIssues() == null || request.unresolvedIssues().isEmpty()) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "partial acceptance requires feedback, corrected output, accepted fields and unresolved issues");
            }
        }
    }

    private boolean blank(String value) {
        return value == null || value.isBlank();
    }

    private String subjectRef(long orderId) {
        return "student-2-order:" + orderId;
    }

    private String json(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JacksonException exception) {
            throw new IllegalStateException("Could not prepare Multi-Agent evidence", exception);
        }
    }

    private String safeMessage(RuntimeException exception) {
        String message = exception.getMessage();
        if (message == null || message.isBlank()) {
            return "service call failed";
        }
        return message.length() > 300 ? message.substring(0, 300) : message;
    }
}
