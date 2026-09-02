package com.smartshop.orders.database.dto;

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

public final class OrderPayloads {

    private OrderPayloads() {}

    public record OrderLineWriteRequest(
        Long id,
        @NotBlank String sku,
        @Min(1) int quantity,
        @DecimalMin("0.00") BigDecimal unitPrice
    ) {}

    public record OrderWriteRequest(
        @NotBlank String orderNumber,
        @NotBlank @Email String customerEmail,
        @NotBlank @Pattern(regexp = "pending|shipped|delivered") String status,
        @NotEmpty List<@Valid OrderLineWriteRequest> lines
    ) {}

    public record OrderUpdateRequest(
        @NotBlank @Email String customerEmail,
        @NotBlank @Pattern(regexp = "pending|shipped|delivered") String status,
        @NotEmpty List<@Valid OrderLineWriteRequest> lines
    ) {}

    public record StatusUpdateRequest(
        @NotBlank @Pattern(regexp = "pending|shipped|delivered") String status
    ) {}

    public record OrderLineResponse(
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
        BigDecimal orderTotal
    ) {}
}
