package com.smartshop.orders.backend.controller;

import com.smartshop.orders.backend.dto.MultiAgentModels.StartWorkflowResponse;
import com.smartshop.orders.backend.dto.MultiAgentModels.WorkflowResponse;
import com.smartshop.orders.backend.exception.ApiExceptionHandler;
import com.smartshop.orders.backend.service.OrderMultiAgentService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.List;
import java.util.Map;

import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class OrderMultiAgentControllerTests {

    private OrderMultiAgentService service;
    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        service = mock(OrderMultiAgentService.class);
        mockMvc = MockMvcBuilders.standaloneSetup(new OrderMultiAgentController(service))
            .setControllerAdvice(new ApiExceptionHandler())
            .build();
    }

    @Test
    void startsTheSharedWorkflowAndReturnsAccepted() throws Exception {
        when(service.start(42L)).thenReturn(new StartWorkflowResponse("wf-42", "queued", null));

        mockMvc.perform(post("/api/orders/{id}/multi-agent", 42L))
            .andExpect(status().isAccepted())
            .andExpect(jsonPath("$.workflow_id").value("wf-42"))
            .andExpect(jsonPath("$.status").value("queued"));
    }

    @Test
    void returnsWorkflowStatusForTheOrder() throws Exception {
        when(service.get(42L, "wf-42")).thenReturn(workflow());

        mockMvc.perform(get("/api/orders/{id}/multi-agent/{workflowId}", 42L, "wf-42"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.subject_ref").value("student-2-order:42"))
            .andExpect(jsonPath("$.status").value("human_review"))
            .andExpect(jsonPath("$.completion_gate.planner_completed").value(true))
            .andExpect(jsonPath("$.completion_gate.worker_completed").value(true))
            .andExpect(jsonPath("$.completion_gate.reviewer_completed").value(true))
            .andExpect(jsonPath("$.completion_gate.human_decision_recorded").value(false));
    }

    @Test
    void forwardsAValidHumanReviewDecision() throws Exception {
        when(service.review(org.mockito.ArgumentMatchers.eq(42L), org.mockito.ArgumentMatchers.eq("wf-42"), argThat(
            request -> "reject".equals(request.decision()) && "Policy conflict".equals(request.feedback())
        ))).thenReturn(workflow());

        mockMvc.perform(post("/api/orders/{id}/multi-agent/{workflowId}/review", 42L, "wf-42")
                .contentType(MediaType.APPLICATION_JSON)
                .content("""
                    {"decision":"reject","feedback":"Policy conflict","unresolved_issues":["Manual review required"]}
                    """))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.workflow_id").value("wf-42"));

        verify(service).review(org.mockito.ArgumentMatchers.eq(42L), org.mockito.ArgumentMatchers.eq("wf-42"),
            argThat(request -> "reject".equals(request.decision())));
    }

    private WorkflowResponse workflow() {
        return new WorkflowResponse(
            "wf-42", "student-2-order:42", "human_review", "human_review",
            Map.of(), Map.of(), Map.of(), null, List.of(), List.of(), 0, 1,
            Map.of(
                "planner_completed", true,
                "worker_completed", true,
                "reviewer_completed", true,
                "human_decision_recorded", false
            ),
            null, null
        );
    }
}
