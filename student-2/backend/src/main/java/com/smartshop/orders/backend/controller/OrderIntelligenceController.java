package com.smartshop.orders.backend.controller;

import com.smartshop.orders.backend.dto.OrderIntelligenceModels.McpToolResponse;
import com.smartshop.orders.backend.dto.OrderIntelligenceModels.RagAnswerResponse;
import com.smartshop.orders.backend.dto.OrderIntelligenceModels.RagQuestionRequest;
import com.smartshop.orders.backend.dto.OrderIntelligenceModels.RagWriteResponse;
import com.smartshop.orders.backend.service.OrderIntelligenceService;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/orders/{orderId}")
public class OrderIntelligenceController {

    private final OrderIntelligenceService intelligenceService;

    public OrderIntelligenceController(OrderIntelligenceService intelligenceService) {
        this.intelligenceService = intelligenceService;
    }

    @PostMapping("/mcp/fulfilment-check")
    public McpToolResponse checkFulfilment(@PathVariable long orderId) {
        return intelligenceService.checkFulfilment(orderId);
    }

    @PostMapping("/rag/refresh")
    public RagWriteResponse refreshRagContext(@PathVariable long orderId) {
        return intelligenceService.refreshContext(orderId);
    }

    @PostMapping("/rag/ask")
    public RagAnswerResponse askRag(
        @PathVariable long orderId,
        @Valid @RequestBody RagQuestionRequest request
    ) {
        return intelligenceService.ask(orderId, request.question());
    }
}
