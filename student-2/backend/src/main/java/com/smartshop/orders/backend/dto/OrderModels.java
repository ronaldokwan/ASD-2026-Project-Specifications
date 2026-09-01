package com.smartshop.orders.backend.dto;

import jakarta.validation.Valid;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.Pattern;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;

public final class OrderModels {

    private OrderModels() {}

    public record OrderLineRequest(
        Long id,
        @NotBlank String sku,
        @Min(1) int quantity,
        @DecimalMin("0.00") BigDecimal unitPrice
    ) {}

    public record OrderRequest(
        @NotBlank @Email String customerEmail,
        @NotBlank @Pattern(regexp = "pending|shipped|delivered") String status,
        @NotEmpty List<@Valid OrderLineRequest> lines
    ) {}

    public record StatusRequest(
        @NotBlank @Pattern(regexp = "pending|shipped|delivered") String status
    ) {}

    public record DatabaseCreateRequest(
        String orderNumber,
        String customerEmail,
        String status,
        List<OrderLineRequest> lines
    ) {}

    public record DatabaseOrder(
        Long id,
        String orderNumber,
        String customerEmail,
        String status,
        LocalDateTime orderedAt,
        LocalDateTime updatedAt,
        List<DatabaseOrderLine> lines,
        BigDecimal orderTotal
    ) {}

    public record DatabaseOrderLine(
        Long id,
        String sku,
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

    public record OrderLineResponse(
        Long id,
        String sku,
        String productName,
        int quantity,
        BigDecimal unitPrice,
        BigDecimal lineTotal
    ) {}

    public record ProductInfo(String sku, String name, BigDecimal price) {}
    public record StockItemRequest(String sku, int quantity) {}
    public record StockCheckResult(boolean sufficient, String message) {}
    public record StockUpdateResult(boolean success, String message) {}
    public record StockCheckRequest(@NotEmpty List<@Valid OrderLineRequest> lines) {}
    public record CustomerSummaryRequest(@NotBlank @Email String customerEmail) {}
    public record AiResponse(String content, boolean generatedByOllama) {}
}
