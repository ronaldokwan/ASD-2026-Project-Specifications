package com.smartshop.orders.backend.exception;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.client.ResourceAccessException;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;

@RestControllerAdvice
public class ApiExceptionHandler {

    @ExceptionHandler(MethodArgumentNotValidException.class)
    ResponseEntity<Map<String, Object>> validation(MethodArgumentNotValidException exception) {
        Map<String, String> fields = new LinkedHashMap<>();
        exception.getBindingResult().getFieldErrors()
            .forEach(error -> fields.putIfAbsent(error.getField(), error.getDefaultMessage()));
        return ResponseEntity.badRequest().body(Map.of(
            "timestamp", Instant.now().toString(),
            "status", 400,
            "error", "Validation failed",
            "fields", fields
        ));
    }

    @ExceptionHandler(ResourceAccessException.class)
    ResponseEntity<Map<String, Object>> unavailable(ResourceAccessException exception) {
        return ResponseEntity.status(HttpStatus.BAD_GATEWAY).body(Map.of(
            "timestamp", Instant.now().toString(),
            "status", 502,
            "error", "Required internal service is unavailable"
        ));
    }
}
