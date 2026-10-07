package com.smartshop.orders.backend.controller;

import com.smartshop.orders.backend.dto.OrderModels.AiResponse;
import com.smartshop.orders.backend.dto.OrderModels.CustomerSummaryRequest;
import com.smartshop.orders.backend.dto.OrderModels.OrderResponse;
import com.smartshop.orders.backend.service.AiService;
import com.smartshop.orders.backend.service.OrderService;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/orders")
public class AiController {

    private final OrderService orderService;
    private final AiService aiService;

    public AiController(OrderService orderService, AiService aiService) {
        this.orderService = orderService;
        this.aiService = aiService;
    }

    @PostMapping("/{id}/ai/delay-email")
    public AiResponse delayEmail(@PathVariable long id) {
        OrderResponse order = orderService.get(id);
        String fallback = "Subject: Update about order " + order.orderNumber()
            + "\n\nWe are sorry that your order has been delayed. "
            + "Our team is working to ship it as soon as possible. Thank you for your patience.";
        return aiService.generate(
            "shipping_delay_email",
            "Draft a concise, polite shipping-delay apology email. Include the order number "
                + "and do not invent a delivery date.",
            Map.of(
                "order_number", order.orderNumber(),
                "status", order.status(),
                "total_quantity", order.totalQuantity()
            ),
            fallback
        );
    }

    @PostMapping("/ai/customer-summary")
    public AiResponse customerSummary(@Valid @RequestBody CustomerSummaryRequest request) {
        List<OrderResponse> orders = orderService.list(null, request.customerEmail(), null);
        String fallback = "Customer " + request.customerEmail() + " has " + orders.size()
            + " recorded order(s) with a combined total of "
            + orders.stream().map(OrderResponse::orderTotal)
                .reduce(java.math.BigDecimal.ZERO, java.math.BigDecimal::add) + ".";
        List<Map<String, Object>> orderHistory = orders.stream()
            .map(order -> Map.<String, Object>of(
                "order_number", order.orderNumber(),
                "status", order.status(),
                "total_quantity", order.totalQuantity(),
                "order_total", order.orderTotal()
            ))
            .toList();
        return aiService.generate(
            "customer_order_summary",
            "Summarise the supplied order history in no more than three concise bullet points. "
                + "Do not invent orders, totals or statuses.",
            Map.of(
                "customer_email", request.customerEmail(),
                "order_count", orders.size(),
                "orders", orderHistory
            ),
            fallback
        );
    }
}
