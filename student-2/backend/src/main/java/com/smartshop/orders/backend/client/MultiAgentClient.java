package com.smartshop.orders.backend.client;

import com.smartshop.orders.backend.dto.MultiAgentModels.ReviewRequest;
import com.smartshop.orders.backend.dto.MultiAgentModels.StartWorkflowRequest;
import com.smartshop.orders.backend.dto.MultiAgentModels.StartWorkflowResponse;
import com.smartshop.orders.backend.dto.MultiAgentModels.WorkflowHistoryResponse;
import com.smartshop.orders.backend.dto.MultiAgentModels.WorkflowResponse;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientResponseException;
import org.springframework.web.client.RestClientException;
import org.springframework.web.server.ResponseStatusException;

import java.time.Duration;

import static org.springframework.http.HttpStatus.BAD_GATEWAY;
import static org.springframework.http.HttpStatus.SERVICE_UNAVAILABLE;

@Component
public class MultiAgentClient {

    private final RestClient client;
    private final boolean enabled;

    @Autowired
    public MultiAgentClient(
        RestClient.Builder builder,
        @Value("${services.multi-agent-url}") String serverUrl,
        @Value("${services.multi-agent-enabled:true}") boolean enabled,
        @Value("${services.multi-agent-timeout-seconds:180}") int timeoutSeconds
    ) {
        SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory();
        requestFactory.setConnectTimeout(Duration.ofSeconds(timeoutSeconds));
        requestFactory.setReadTimeout(Duration.ofSeconds(timeoutSeconds));
        this.client = builder.clone().baseUrl(serverUrl).requestFactory(requestFactory).build();
        this.enabled = enabled;
    }

    MultiAgentClient(RestClient client, boolean enabled) {
        this.client = client;
        this.enabled = enabled;
    }

    public StartWorkflowResponse start(StartWorkflowRequest request) {
        requireEnabled();
        try {
            StartWorkflowResponse response = client.post().uri("/workflow")
                .contentType(MediaType.APPLICATION_JSON)
                .body(request)
                .retrieve().body(StartWorkflowResponse.class);
            if (response == null || response.workflowId() == null || response.workflowId().isBlank()) {
                throw invalidResponse("missing workflow ID");
            }
            return response;
        } catch (ResponseStatusException exception) {
            throw exception;
        } catch (RestClientResponseException exception) {
            throw downstreamFailure(exception);
        } catch (RestClientException exception) {
            throw unavailable(exception);
        }
    }

    public WorkflowResponse get(String workflowId) {
        requireEnabled();
        try {
            WorkflowResponse response = client.get().uri("/workflow/{id}", workflowId)
                .retrieve().body(WorkflowResponse.class);
            if (response == null || response.workflowId() == null || response.status() == null) {
                throw invalidResponse("missing workflow status");
            }
            return response;
        } catch (ResponseStatusException exception) {
            throw exception;
        } catch (RestClientResponseException exception) {
            throw downstreamFailure(exception);
        } catch (RestClientException exception) {
            throw unavailable(exception);
        }
    }

    public WorkflowHistoryResponse history(String subjectRef) {
        requireEnabled();
        try {
            WorkflowHistoryResponse response = client.get()
                .uri(builder -> builder.path("/workflow/history")
                    .queryParam("subject_ref", subjectRef).build())
                .retrieve().body(WorkflowHistoryResponse.class);
            if (response == null || response.workflows() == null) {
                throw invalidResponse("missing workflow history");
            }
            return response;
        } catch (ResponseStatusException exception) {
            throw exception;
        } catch (RestClientResponseException exception) {
            throw downstreamFailure(exception);
        } catch (RestClientException exception) {
            throw unavailable(exception);
        }
    }

    public WorkflowResponse review(String workflowId, ReviewRequest request) {
        requireEnabled();
        try {
            WorkflowResponse response = client.post().uri("/workflow/{id}/review", workflowId)
                .contentType(MediaType.APPLICATION_JSON)
                .body(request)
                .retrieve().body(WorkflowResponse.class);
            if (response == null || response.workflowId() == null || response.status() == null) {
                throw invalidResponse("missing reviewed workflow");
            }
            return response;
        } catch (ResponseStatusException exception) {
            throw exception;
        } catch (RestClientResponseException exception) {
            throw downstreamFailure(exception);
        } catch (RestClientException exception) {
            throw unavailable(exception);
        }
    }

    private void requireEnabled() {
        if (!enabled) {
            throw new ResponseStatusException(SERVICE_UNAVAILABLE, "Multi-Agent integration is disabled");
        }
    }

    private ResponseStatusException downstreamFailure(RestClientResponseException exception) {
        if (exception.getStatusCode().is5xxServerError()) {
            return unavailable(exception);
        }
        return new ResponseStatusException(
            exception.getStatusCode(), "Shared Multi-Agent service rejected the request", exception
        );
    }

    private ResponseStatusException unavailable(Exception exception) {
        return new ResponseStatusException(
            SERVICE_UNAVAILABLE, "Shared Multi-Agent service is unavailable", exception
        );
    }

    private ResponseStatusException invalidResponse(String reason) {
        return new ResponseStatusException(
            BAD_GATEWAY, "Shared Multi-Agent service returned an invalid result: " + reason
        );
    }
}
