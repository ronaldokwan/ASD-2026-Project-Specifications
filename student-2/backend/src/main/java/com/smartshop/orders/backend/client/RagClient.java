package com.smartshop.orders.backend.client;

import com.smartshop.orders.backend.dto.OrderIntelligenceModels.RagAnswerResponse;
import com.smartshop.orders.backend.dto.OrderIntelligenceModels.RagDocument;
import com.smartshop.orders.backend.dto.OrderIntelligenceModels.RagDocumentsRequest;
import com.smartshop.orders.backend.dto.OrderIntelligenceModels.RagQueryRequest;
import com.smartshop.orders.backend.dto.OrderIntelligenceModels.RagWriteResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.server.ResponseStatusException;

import java.time.Duration;
import java.util.List;
import java.util.Map;

import static org.springframework.http.HttpStatus.SERVICE_UNAVAILABLE;

@Component
public class RagClient {

    private final RestClient client;
    private final boolean enabled;

    @Autowired
    public RagClient(
        RestClient.Builder builder,
        @Value("${services.rag-server-url}") String serverUrl,
        @Value("${services.rag-enabled:true}") boolean enabled,
        @Value("${services.rag-timeout-seconds:120}") int timeoutSeconds
    ) {
        SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory();
        requestFactory.setConnectTimeout(Duration.ofSeconds(timeoutSeconds));
        requestFactory.setReadTimeout(Duration.ofSeconds(timeoutSeconds));
        this.client = builder.clone().baseUrl(serverUrl).requestFactory(requestFactory).build();
        this.enabled = enabled;
    }

    RagClient(RestClient client, boolean enabled) {
        this.client = client;
        this.enabled = enabled;
    }

    public RagWriteResponse upsertDocuments(List<RagDocument> documents) {
        requireEnabled();
        RagWriteResponse response = client.post()
            .uri("/rag/documents")
            .contentType(MediaType.APPLICATION_JSON)
            .body(new RagDocumentsRequest(documents))
            .retrieve()
            .body(RagWriteResponse.class);
        if (response == null || !response.ok()) {
            throw invalidResponse(response == null ? null : response.error());
        }
        return response;
    }

    public RagWriteResponse deleteDocument(String documentId) {
        requireEnabled();
        RagWriteResponse response = client.delete()
            .uri("/rag/documents/{id}", documentId)
            .retrieve()
            .body(RagWriteResponse.class);
        if (response == null || !response.ok()) {
            throw invalidResponse(response == null ? null : response.error());
        }
        return response;
    }

    public RagAnswerResponse ask(String question, String orderNumber) {
        requireEnabled();
        Map<String, Object> filters = Map.of(
            "$and", List.of(
                Map.of("feature", "orders"),
                Map.of("$or", List.of(
                    Map.of("order_number", orderNumber),
                    Map.of("doc_type", "shipping_policy")
                ))
            )
        );
        RagAnswerResponse response = client.post()
            .uri("/rag/query")
            .contentType(MediaType.APPLICATION_JSON)
            .body(new RagQueryRequest(question, 5, filters))
            .retrieve()
            .body(RagAnswerResponse.class);
        if (response == null || response.status() == null) {
            throw invalidResponse(response == null ? null : response.error());
        }
        return response;
    }

    private void requireEnabled() {
        if (!enabled) {
            throw new ResponseStatusException(SERVICE_UNAVAILABLE, "RAG mode is disabled");
        }
    }

    private ResponseStatusException invalidResponse(String detail) {
        return new ResponseStatusException(
            SERVICE_UNAVAILABLE,
            "Shared RAG server returned an invalid result" + (detail == null ? "" : ": " + detail)
        );
    }
}
