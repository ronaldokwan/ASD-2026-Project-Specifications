package com.smartshop.orders.backend.service;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.smartshop.orders.backend.dto.OrderModels.AiResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

import java.util.Map;

@Service
public class AiService {

    private final RestClient ollamaClient;
    private final RestClient aiModeClient;
    private final String model;

    public AiService(
        RestClient.Builder builder,
        @Value("${services.ollama-url}") String ollamaUrl,
        @Value("${services.ai-mode-url}") String aiModeUrl,
        @Value("${services.ollama-model}") String model
    ) {
        this.ollamaClient = builder.baseUrl(ollamaUrl).build();
        this.aiModeClient = builder.clone().baseUrl(aiModeUrl).build();
        this.model = model;
    }

    public AiResponse generate(String prompt, String fallback) {
        try {
            OllamaResponse response = ollamaClient.post().uri("/api/generate")
                .contentType(MediaType.APPLICATION_JSON)
                .body(Map.of("model", model, "prompt", prompt, "stream", false))
                .retrieve()
                .body(OllamaResponse.class);
            if (response != null && response.response() != null && !response.response().isBlank()) {
                return new AiResponse(response.response(), true);
            }
        } catch (RuntimeException ignored) {
            // The order feature stays demonstrable while the shared Ollama service is unavailable.
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
    private record OllamaResponse(String response) {}
}
