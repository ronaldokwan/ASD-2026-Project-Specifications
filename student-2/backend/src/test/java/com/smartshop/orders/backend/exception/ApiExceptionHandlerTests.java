package com.smartshop.orders.backend.exception;

import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

import static org.assertj.core.api.Assertions.assertThat;

class ApiExceptionHandlerTests {

    private final ApiExceptionHandler handler = new ApiExceptionHandler();

    @Test
    void includesTheBusinessReasonInResponseStatusErrors() {
        var response = handler.responseStatus(new ResponseStatusException(
            HttpStatus.CONFLICT,
            "Insufficient stock for SKU SKU-AUD-1001 (available 50, requested 1000)"
        ));

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.CONFLICT);
        assertThat(response.getBody())
            .containsEntry("status", 409)
            .containsEntry("error", "Conflict")
            .containsEntry(
                "message",
                "Insufficient stock for SKU SKU-AUD-1001 (available 50, requested 1000)"
            );
    }
}
