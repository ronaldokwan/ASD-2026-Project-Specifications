package com.smartshop.orders.backend.client;

import com.smartshop.orders.backend.dto.OrderIntelligenceModels.FulfilmentRequest;
import com.smartshop.orders.backend.dto.OrderIntelligenceModels.FulfilmentResult;
import com.smartshop.orders.backend.dto.OrderIntelligenceModels.McpToolResponse;
import io.modelcontextprotocol.client.McpSyncClient;
import io.modelcontextprotocol.client.transport.HttpClientStreamableHttpTransport;
import io.modelcontextprotocol.spec.McpSchema.CallToolRequest;
import io.modelcontextprotocol.spec.McpSchema.CallToolResult;
import io.modelcontextprotocol.spec.McpSchema.TextContent;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ResponseStatusException;

import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.springframework.http.HttpStatus.SERVICE_UNAVAILABLE;

@Component
public class McpClient {

    private static final String TOOL_NAME = "check_order_fulfilment";

    private final ToolInvoker toolInvoker;
    private final boolean enabled;

    @Autowired
    public McpClient(
        @Value("${services.mcp-server-url}") String serverUrl,
        @Value("${services.mcp-enabled:true}") boolean enabled,
        @Value("${services.mcp-timeout-seconds:15}") int timeoutSeconds
    ) {
        String baseUrl = serverUrl.replaceAll("/+$", "");
        Duration timeout = Duration.ofSeconds(timeoutSeconds);
        this.toolInvoker = request -> {
            var transport = HttpClientStreamableHttpTransport.builder(baseUrl)
                .endpoint("/mcp")
                .connectTimeout(timeout)
                .build();
            try (McpSyncClient client = io.modelcontextprotocol.client.McpClient.sync(transport)
                .initializationTimeout(timeout)
                .requestTimeout(timeout)
                .build()) {
                client.initialize();
                return client.callTool(request);
            }
        };
        this.enabled = enabled;
    }

    McpClient(ToolInvoker toolInvoker, boolean enabled) {
        this.toolInvoker = toolInvoker;
        this.enabled = enabled;
    }

    public McpToolResponse checkOrderFulfilment(FulfilmentRequest request) {
        requireEnabled();

        Map<String, Object> arguments = new LinkedHashMap<>();
        arguments.put("order_number", request.orderNumber());
        arguments.put("status", request.status());
        arguments.put("line_count", request.lineCount());
        arguments.put("total_quantity", request.totalQuantity());
        arguments.put("order_total", request.orderTotal());
        arguments.put("inventory_committed", request.inventoryCommitted());

        CallToolResult response;
        try {
            response = toolInvoker.call(CallToolRequest.builder(TOOL_NAME)
                .arguments(arguments)
                .build());
        } catch (RuntimeException exception) {
            throw new ResponseStatusException(
                SERVICE_UNAVAILABLE,
                "Shared MCP server is unavailable",
                exception
            );
        }

        if (response == null || Boolean.TRUE.equals(response.isError())) {
            throw invalidResponse(response == null ? "empty response" : errorText(response));
        }

        FulfilmentResult result = structuredResult(response.structuredContent());
        return new McpToolResponse(true, TOOL_NAME, result, null);
    }

    private FulfilmentResult structuredResult(Object structuredContent) {
        if (!(structuredContent instanceof Map<?, ?> content)) {
            throw invalidResponse("missing structured tool result");
        }

        Object readyToShip = content.get("ready_to_ship");
        Object summary = content.get("summary");
        if (!(readyToShip instanceof Boolean) || !(summary instanceof String summaryText)) {
            throw invalidResponse("structured tool result does not match the fulfilment contract");
        }

        return new FulfilmentResult(
            (Boolean) readyToShip,
            stringList(content.get("blockers")),
            stringList(content.get("checked_rules")),
            summaryText
        );
    }

    private List<String> stringList(Object value) {
        if (!(value instanceof List<?> values)
            || values.stream().anyMatch(item -> !(item instanceof String))) {
            throw invalidResponse("structured tool result contains an invalid list");
        }
        return values.stream().map(String.class::cast).toList();
    }

    private String errorText(CallToolResult response) {
        return response.content().stream()
            .filter(TextContent.class::isInstance)
            .map(TextContent.class::cast)
            .map(TextContent::text)
            .findFirst()
            .orElse("tool execution failed");
    }

    private ResponseStatusException invalidResponse(String reason) {
        return new ResponseStatusException(
            SERVICE_UNAVAILABLE,
            "Shared MCP server returned an invalid result: " + reason
        );
    }

    private void requireEnabled() {
        if (!enabled) {
            throw new ResponseStatusException(SERVICE_UNAVAILABLE, "MCP mode is disabled");
        }
    }

    @FunctionalInterface
    interface ToolInvoker {
        CallToolResult call(CallToolRequest request);
    }
}
