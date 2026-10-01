package com.smartshop.orders.backend.client;

import com.smartshop.orders.backend.dto.OrderIntelligenceModels.FulfilmentRequest;
import com.smartshop.orders.backend.dto.OrderIntelligenceModels.McpToolResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.server.ResponseStatusException;

import java.time.Duration;

import static org.springframework.http.HttpStatus.SERVICE_UNAVAILABLE;

@Component
public class McpClient {

    private final RestClient client;
    private final boolean enabled;

    @Autowired
    public McpClient(
        RestClient.Builder builder,
        @Value("${services.mcp-server-url}") String serverUrl,
        @Value("${services.mcp-enabled:true}") boolean enabled,
        @Value("${services.mcp-timeout-seconds:15}") int timeoutSeconds
    ) {
        SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory();
        requestFactory.setConnectTimeout(Duration.ofSeconds(timeoutSeconds));
        requestFactory.setReadTimeout(Duration.ofSeconds(timeoutSeconds));
        this.client = builder.clone().baseUrl(serverUrl).requestFactory(requestFactory).build();
        this.enabled = enabled;
    }

    McpClient(RestClient client, boolean enabled) {
        this.client = client;
        this.enabled = enabled;
    }

    public McpToolResponse checkOrderFulfilment(FulfilmentRequest request) {
        requireEnabled();
        McpToolResponse response = client.post()
            .uri("/tools/check_order_fulfilment")
            .contentType(MediaType.APPLICATION_JSON)
            .body(request)
            .retrieve()
            .body(McpToolResponse.class);
        if (response == null || !response.ok() || response.result() == null) {
            String reason = response == null ? "empty response" : response.error();
            throw new ResponseStatusException(
                SERVICE_UNAVAILABLE,
                "Shared MCP server returned an invalid result" + (reason == null ? "" : ": " + reason)
            );
        }
        return response;
    }

    private void requireEnabled() {
        if (!enabled) {
            throw new ResponseStatusException(SERVICE_UNAVAILABLE, "MCP mode is disabled");
        }
    }
}
