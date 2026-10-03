package com.smartshop.orders.backend.service;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.smartshop.orders.backend.dto.OrderModels.AiResponse;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

import java.util.Map;

@Service
public class AiService {

    private static final Map<String, Object> CONTENT_SCHEMA = Map.of(
        "content", Map.of(
            "type", "string",
            "min_words", 8,
            "max_words", 120,
            "hint", "Use only the supplied context facts and follow the task exactly."
        )
    );

    private final RestClient aiModeClient;

    @Autowired
    public AiService(
        RestClient.Builder builder,
        @Value("${services.ai-mode-url}") String aiModeUrl
    ) {
        this(builder.clone().baseUrl(aiModeUrl).build());
    }

    AiService(RestClient aiModeClient) {
        this.aiModeClient = aiModeClient;
    }

    public AiResponse generate(
        String goal,
        String task,
        Map<String, Object> context,
        String fallback
    ) {
        try {
            AgentResponse response = aiModeClient.post().uri("/agent/run")
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of(
                    "goal", goal,
                    "task", task,
                    "context", context,
                    "output_schema", CONTENT_SCHEMA,
                    "fallback", Map.of("content", fallback)
                ))
                .retrieve()
                .body(AgentResponse.class);
            if (response != null && response.ok() && response.result() != null) {
                Object content = response.result().get("content");
                if (content instanceof String text && !text.isBlank()) {
                    return new AiResponse(text, !response.fallbackUsed());
                }
            }
        } catch (RuntimeException ignored) {
            // Keep the feature usable with its deterministic fallback if AI-Mode is offline.
        }
        return new AiResponse(fallback, false);
    }

    public Map<String, Object> health() {
        try {
            Map<String, Object> response = aiModeClient.get().uri("/health")
                .retrieve().body(new org.springframework.core.ParameterizedTypeReference<>() {});
            return response == null ? Map.of("status", "unreachable") : response;
        } catch (RuntimeException exception) {
            return Map.of(
                "status", "unreachable",
                "error", exception.getMessage() == null ? "AI-Mode health check failed" : exception.getMessage()
            );
        }
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    private record AgentResponse(
        boolean ok,
        Map<String, Object> result,
        @JsonProperty("fallback_used") boolean fallbackUsed
    ) {}
}
