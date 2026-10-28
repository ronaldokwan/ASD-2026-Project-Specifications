package com.smartshop.orders.backend.client;

import com.smartshop.orders.backend.dto.MultiAgentModels.Evidence;
import com.smartshop.orders.backend.dto.MultiAgentModels.PlanContract;
import com.smartshop.orders.backend.dto.MultiAgentModels.StartWorkflowRequest;
import com.smartshop.orders.backend.dto.MultiAgentModels.WorkflowRequest;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.ExpectedCount.once;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.content;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

class MultiAgentClientTests {

    private MockRestServiceServer server;
    private MultiAgentClient client;

    @BeforeEach
    void setUp() {
        RestClient.Builder builder = RestClient.builder().baseUrl("http://multi-agent:7004");
        server = MockRestServiceServer.bindTo(builder).build();
        client = new MultiAgentClient(builder.build(), true);
    }

    @Test
    void startsAWorkflowUsingTheSharedContract() {
        server.expect(once(), requestTo("http://multi-agent:7004/workflow"))
            .andExpect(content().json("""
                {
                  "subject_ref":"student-2-order:42",
                  "request":{"goal":"Review shipment"},
                  "evidence":[{"id":"order_facts","source":"orders","status":"available","meaning":"facts","content":"{}"}],
                  "max_revisions":1
                }
                """, false))
            .andRespond(withSuccess(
                "{\"workflow_id\":\"wf-42\",\"status\":\"queued\"}",
                MediaType.APPLICATION_JSON
            ));

        var response = client.start(request());

        assertThat(response.workflowId()).isEqualTo("wf-42");
        assertThat(response.status()).isEqualTo("queued");
        server.verify();
    }

    @Test
    void rejectsAnInvalidSharedServiceResponse() {
        server.expect(once(), requestTo("http://multi-agent:7004/workflow"))
            .andRespond(withSuccess("{\"status\":\"queued\"}", MediaType.APPLICATION_JSON));

        assertThatThrownBy(() -> client.start(request()))
            .isInstanceOf(ResponseStatusException.class)
            .hasMessageContaining("missing workflow ID");
    }

    @Test
    void preservesTheCompletionGateNeededByAgenticLoopReview() {
        server.expect(once(), requestTo("http://multi-agent:7004/workflow/wf-42"))
            .andRespond(withSuccess("""
                {
                  "workflow_id":"wf-42",
                  "subject_ref":"student-2-order:42",
                  "status":"accepted",
                  "stage":"completed",
                  "completion_gate":{
                    "planner_completed":true,
                    "worker_completed":true,
                    "reviewer_completed":true,
                    "human_decision_recorded":true
                  }
                }
                """, MediaType.APPLICATION_JSON));

        var response = client.get("wf-42");

        assertThat(response.completionGate())
            .containsEntry("planner_completed", true)
            .containsEntry("worker_completed", true)
            .containsEntry("reviewer_completed", true)
            .containsEntry("human_decision_recorded", true);
        server.verify();
    }

    @Test
    void refusesCallsWhenMultiAgentModeIsDisabled() {
        MultiAgentClient disabled = new MultiAgentClient(RestClient.create(), false);

        assertThatThrownBy(() -> disabled.start(request()))
            .isInstanceOf(ResponseStatusException.class)
            .hasMessageContaining("disabled");
    }

    private StartWorkflowRequest request() {
        return new StartWorkflowRequest(
            "student-2-order:42",
            new WorkflowRequest(
                "Review shipment",
                new PlanContract(List.of("Check order"), List.of("No mutation")),
                List.of("order_facts"),
                List.of("order_facts"),
                List.of()
            ),
            List.of(new Evidence("order_facts", "orders", "available", "facts", "{}")),
            1
        );
    }
}
