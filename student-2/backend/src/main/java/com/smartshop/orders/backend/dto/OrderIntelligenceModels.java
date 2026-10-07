package com.smartshop.orders.backend.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

import java.util.List;
import java.util.Map;

public final class OrderIntelligenceModels {

    private OrderIntelligenceModels() {}

    public record FulfilmentRequest(
        @JsonProperty("order_number") String orderNumber,
        String status,
        @JsonProperty("line_count") int lineCount,
        @JsonProperty("total_quantity") int totalQuantity,
        @JsonProperty("order_total") java.math.BigDecimal orderTotal,
        @JsonProperty("inventory_committed") boolean inventoryCommitted
    ) {}

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

    public record RagQuestionRequest(
        @NotBlank(message = "question is required")
        @Size(max = 500, message = "question must not exceed 500 characters")
        String question
    ) {}

    public record RagDocument(String id, String text, Map<String, Object> metadata) {}

    public record RagDocumentsRequest(List<RagDocument> documents) {}

    public record RagQueryRequest(
        String query,
        @JsonProperty("top_k") int topK,
        Map<String, Object> filters
    ) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record RagWriteResponse(
        boolean ok,
        @JsonProperty("documents_indexed") Integer documentsIndexed,
        @JsonProperty("chunks_indexed") Integer chunksIndexed,
        @JsonProperty("chunks_removed") Integer chunksRemoved,
        String error
    ) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record RagAnswerResponse(
        String status,
        String answer,
        String message,
        String confidence,
        List<RagSource> sources,
        @JsonProperty("retrieved_count") Integer retrievedCount,
        @JsonProperty("elapsed_ms") Integer elapsedMs,
        String error
    ) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record RagSource(
        @JsonProperty("doc_id") String docId,
        @JsonProperty("chunk_id") String chunkId,
        String snippet,
        Map<String, Object> metadata
    ) {}
}
