package com.smartshop.orders.frontend.controller;

import com.smartshop.orders.frontend.client.BackendClient;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;

@RestController
public class HealthController {

    private final BackendClient backend;

    public HealthController(BackendClient backend) {
        this.backend = backend;
    }

    @GetMapping("/health")
    public ResponseEntity<Map<String, Object>> health() {
        Map<String, Object> downstream;
        boolean healthy;
        try {
            downstream = backend.health();
            healthy = downstream != null && "ok".equals(downstream.get("status"));
        } catch (RuntimeException exception) {
            downstream = Map.of(
                "status", "unreachable",
                "error", safeMessage(exception)
            );
            healthy = false;
        }

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("service", "student-2-frontend");
        body.put("student", 2);
        body.put("owner", "Jinying Li");
        body.put("feature", "Customer Orders");
        body.put("status", healthy ? "ok" : "degraded");
        body.put("backend", downstream);
        return ResponseEntity.status(healthy ? HttpStatus.OK : HttpStatus.SERVICE_UNAVAILABLE)
            .body(body);
    }

    private String safeMessage(RuntimeException exception) {
        return exception.getMessage() == null ? "Backend health check failed" : exception.getMessage();
    }
}
