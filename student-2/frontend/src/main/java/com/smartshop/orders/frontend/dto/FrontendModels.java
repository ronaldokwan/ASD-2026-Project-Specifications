package com.smartshop.orders.frontend.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;

public final class FrontendModels {

    private FrontendModels() {}

    public record OrderLineRequest(Long id, String sku, int quantity, BigDecimal unitPrice) {}
    public record OrderRequest(String customerEmail, String status, List<OrderLineRequest> lines) {}
    public record StatusRequest(String status) {}
    public record CustomerSummaryRequest(String customerEmail) {}
    public record ProductInfo(String sku, String name, BigDecimal price) {}

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

    public record AiResponse(String content, boolean generatedByAiMode) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record McpToolResponse(
        boolean ok,
        String tool,
        FulfilmentResult result,
        String error
    ) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record FulfilmentResult(
        @JsonProperty("ready_to_ship") boolean readyToShip,
        List<String> blockers,
        @JsonProperty("checked_rules") List<String> checkedRules,
        String summary
    ) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record RagWriteResponse(
        boolean ok,
        @JsonProperty("documents_indexed") Integer documentsIndexed,
        @JsonProperty("chunks_indexed") Integer chunksIndexed,
        String error
    ) {}

    public record RagQuestionRequest(String question) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record RagAnswerResponse(
        String status,
        String answer,
        String message,
        String confidence,
        List<RagSource> sources,
        String error
    ) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record RagSource(
        @JsonProperty("doc_id") String docId,
        String snippet
    ) {}

    public record RagSourceView(
        String docId,
        String label,
        List<String> snippets
    ) {}
}
