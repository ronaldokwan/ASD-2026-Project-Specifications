package com.smartshop.orders.frontend.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

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

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record StartWorkflowResponse(
        @JsonProperty("workflow_id") String workflowId,
        String status,
        String error
    ) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record MultiAgentEvidence(
        String id,
        String source,
        String status,
        String meaning,
        String content
    ) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record MultiAgentWorkflow(
        @JsonProperty("workflow_id") String workflowId,
        @JsonProperty("subject_ref") String subjectRef,
        String status,
        String stage,
        Map<String, Object> plan,
        @JsonProperty("worker_result") Map<String, Object> workerResult,
        @JsonProperty("reviewer_result") Map<String, Object> reviewerResult,
        @JsonProperty("human_decision") Map<String, Object> humanDecision,
        List<Map<String, Object>> roles,
        List<MultiAgentEvidence> evidence,
        @JsonProperty("revision_count") Integer revisionCount,
        @JsonProperty("max_revisions") Integer maxRevisions,
        String failure,
        String error
    ) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record MultiAgentHistory(
        int count,
        List<MultiAgentWorkflow> workflows,
        String error
    ) {}

    public record MultiAgentReviewRequest(
        String decision,
        String feedback,
        @JsonProperty("accepted_fields") List<String> acceptedFields,
        @JsonProperty("unresolved_issues") List<String> unresolvedIssues,
        @JsonProperty("corrected_output") Map<String, String> correctedOutput
    ) {}
}
