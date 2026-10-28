package com.smartshop.orders.backend.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

import java.util.List;
import java.util.Map;

public final class MultiAgentModels {

    private MultiAgentModels() {}

    public record Evidence(
        String id,
        String source,
        String status,
        String meaning,
        String content
    ) {}

    public record PlanContract(
        @JsonProperty("acceptance_criteria") List<String> acceptanceCriteria,
        List<String> constraints
    ) {}

    public record WorkflowRequest(
        String goal,
        @JsonProperty("plan_contract") PlanContract planContract,
        @JsonProperty("worker_evidence_ids") List<String> workerEvidenceIds,
        @JsonProperty("worker_required_evidence_ids") List<String> workerRequiredEvidenceIds,
        @JsonProperty("worker_policy_evidence_ids") List<String> workerPolicyEvidenceIds
    ) {}

    public record StartWorkflowRequest(
        @JsonProperty("subject_ref") String subjectRef,
        WorkflowRequest request,
        List<Evidence> evidence,
        @JsonProperty("max_revisions") int maxRevisions
    ) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record StartWorkflowResponse(
        @JsonProperty("workflow_id") String workflowId,
        String status,
        String error
    ) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record WorkflowResponse(
        @JsonProperty("workflow_id") String workflowId,
        @JsonProperty("subject_ref") String subjectRef,
        String status,
        String stage,
        Map<String, Object> plan,
        @JsonProperty("worker_result") Map<String, Object> workerResult,
        @JsonProperty("reviewer_result") Map<String, Object> reviewerResult,
        @JsonProperty("human_decision") Map<String, Object> humanDecision,
        List<Map<String, Object>> roles,
        List<Evidence> evidence,
        @JsonProperty("revision_count") Integer revisionCount,
        @JsonProperty("max_revisions") Integer maxRevisions,
        @JsonProperty("completion_gate") Map<String, Boolean> completionGate,
        String failure,
        String error
    ) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record WorkflowHistoryResponse(
        int count,
        List<WorkflowResponse> workflows,
        String error
    ) {}

    public record ReviewRequest(
        @NotBlank(message = "decision is required")
        @Pattern(regexp = "accept|partial_accept|reject", message = "decision is not supported")
        String decision,
        @Size(max = 2000, message = "feedback must not exceed 2000 characters")
        String feedback,
        @JsonProperty("accepted_fields") List<String> acceptedFields,
        @JsonProperty("unresolved_issues") List<String> unresolvedIssues,
        @JsonProperty("corrected_output") Map<String, String> correctedOutput
    ) {}
}
