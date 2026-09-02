package com.smartshop.orders.frontend.dto;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;

public final class FrontendModels {

    private FrontendModels() {}

    public record OrderLineRequest(Long id, String sku, int quantity, BigDecimal unitPrice) {}
    public record OrderRequest(String customerEmail, String status, List<OrderLineRequest> lines) {}
    public record StatusRequest(String status) {}
    public record CustomerSummaryRequest(String customerEmail) {}

    public record OrderLineResponse(
        Long id,
        String sku,
        String productName,
        int quantity,
        BigDecimal unitPrice,
        BigDecimal lineTotal
    ) {}

    public record OrderResponse(
        Long id,
        String orderNumber,
        String customerEmail,
        String status,
        LocalDateTime orderedAt,
        LocalDateTime updatedAt,
        List<OrderLineResponse> lines,
        int totalQuantity,
        BigDecimal orderTotal
    ) {}

    public record AiResponse(String content, boolean generatedByOllama) {}
}
