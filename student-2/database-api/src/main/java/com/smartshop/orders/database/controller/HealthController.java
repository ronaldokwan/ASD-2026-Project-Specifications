package com.smartshop.orders.database.controller;

import com.smartshop.orders.database.repository.OrderRepository;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;

@RestController
public class HealthController {

    private final OrderRepository orderRepository;
    private final String databaseUrl;

    public HealthController(
        OrderRepository orderRepository,
        @Value("${spring.datasource.url}") String databaseUrl
    ) {
        this.orderRepository = orderRepository;
        this.databaseUrl = databaseUrl;
    }

    @GetMapping("/health")
    public ResponseEntity<Map<String, Object>> health() {
        try {
            long orders = orderRepository.count();
            Map<String, Object> body = metadata("ok");
            body.put("db_path", databaseUrl.replaceFirst("^jdbc:sqlite:", ""));
            body.put("orders", orders);
            return ResponseEntity.ok(body);
        } catch (RuntimeException exception) {
            Map<String, Object> body = metadata("error");
            body.put("error", exception.getMessage() == null ? "Database health check failed" : exception.getMessage());
            return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE).body(body);
        }
    }

    private Map<String, Object> metadata(String status) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("service", "student-2-db");
        body.put("student", 2);
        body.put("owner", "Jinying Li");
        body.put("feature", "Customer Orders");
        body.put("status", status);
        return body;
    }
}
