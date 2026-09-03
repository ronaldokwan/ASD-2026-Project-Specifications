package com.smartshop.orders.backend.controller;

import com.smartshop.orders.backend.client.DatabaseApiClient;
import com.smartshop.orders.backend.service.AiService;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;

@RestController
public class HealthController {

    private final DatabaseApiClient databaseApi;
    private final AiService aiService;

    public HealthController(DatabaseApiClient databaseApi, AiService aiService) {
        this.databaseApi = databaseApi;
        this.aiService = aiService;
    }

    @GetMapping("/health")
    public ResponseEntity<Map<String, Object>> health() {
        Map<String, Object> database;
        boolean databaseHealthy;
        try {
            database = databaseApi.health();
            databaseHealthy = database != null && "ok".equals(database.get("status"));
        } catch (RuntimeException exception) {
            database = Map.of(
                "status", "unreachable",
                "error", safeMessage(exception)
            );
            databaseHealthy = false;
        }

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("service", "student-2-backend");
        body.put("student", 2);
        body.put("owner", "Jinying Li");
        body.put("feature", "Customer Orders");
        body.put("status", databaseHealthy ? "ok" : "degraded");
        body.put("database", database);
        body.put("ai_mode", aiService.health());
        return ResponseEntity.status(databaseHealthy ? HttpStatus.OK : HttpStatus.SERVICE_UNAVAILABLE)
            .body(body);
    }

    private String safeMessage(RuntimeException exception) {
        return exception.getMessage() == null ? "Database health check failed" : exception.getMessage();
    }
}
