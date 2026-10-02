package com.smartshop.orders.backend.service;

import com.smartshop.orders.backend.client.McpClient;
import com.smartshop.orders.backend.dto.OrderIntelligenceModels.FulfilmentRequest;
import com.smartshop.orders.backend.dto.OrderIntelligenceModels.McpToolResponse;
import com.smartshop.orders.backend.dto.OrderIntelligenceModels.RagAnswerResponse;
import com.smartshop.orders.backend.dto.OrderIntelligenceModels.RagWriteResponse;
import com.smartshop.orders.backend.dto.OrderModels.OrderResponse;
import org.springframework.stereotype.Service;

@Service
public class OrderIntelligenceService {

    private final OrderService orderService;
    private final McpClient mcpClient;
    private final OrderRagService ragService;

    public OrderIntelligenceService(
        OrderService orderService,
        McpClient mcpClient,
        OrderRagService ragService
    ) {
        this.orderService = orderService;
        this.mcpClient = mcpClient;
        this.ragService = ragService;
    }

    public McpToolResponse checkFulfilment(long orderId) {
        OrderResponse order = orderService.get(orderId);
        return mcpClient.checkOrderFulfilment(new FulfilmentRequest(
            order.orderNumber(),
            order.status(),
            order.lines().size(),
            order.totalQuantity(),
            order.orderTotal(),
            true
        ));
    }

    public RagWriteResponse refreshContext(long orderId) {
        return ragService.syncOrder(orderService.get(orderId));
    }

    public RagAnswerResponse ask(long orderId, String question) {
        return ragService.ask(orderService.get(orderId), question);
    }
}
