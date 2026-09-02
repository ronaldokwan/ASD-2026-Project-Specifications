package com.smartshop.orders.backend.client;

import com.smartshop.orders.backend.dto.OrderModels.DatabaseCreateRequest;
import com.smartshop.orders.backend.dto.OrderModels.DatabaseOrder;
import com.smartshop.orders.backend.dto.OrderModels.DatabaseOrderLine;
import com.smartshop.orders.backend.dto.OrderModels.OrderLineRequest;
import com.smartshop.orders.backend.dto.OrderModels.OrderRequest;
import com.smartshop.orders.backend.dto.OrderModels.StatusRequest;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientResponseException;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;

@Component
public class DatabaseApiClient {

    private final RestClient restClient;

    public DatabaseApiClient(
        RestClient.Builder builder,
        @Value("${services.database-api-url}") String databaseApiUrl
    ) {
        this.restClient = builder.baseUrl(databaseApiUrl).build();
    }

    public List<DatabaseOrder> list(String status, String customerEmail, String orderNumber) {
        try {
            return restClient.get()
                .uri(uriBuilder -> uriBuilder.path("/internal/orders")
                    .queryParamIfPresent("status", optionalText(status))
                    .queryParamIfPresent("customerEmail", optionalText(customerEmail))
                    .queryParamIfPresent("orderNumber", optionalText(orderNumber))
                    .build())
                .retrieve()
                .body(new ParameterizedTypeReference<>() {});
        } catch (RestClientResponseException exception) {
            throw translate(exception);
        }
    }

    public DatabaseOrder get(long id) {
        try {
            return restClient.get().uri("/internal/orders/{id}", id)
                .retrieve().body(DatabaseOrder.class);
        } catch (RestClientResponseException exception) {
            throw translate(exception);
        }
    }

    public DatabaseOrder create(DatabaseCreateRequest request) {
        try {
            return restClient.post().uri("/internal/orders")
                .contentType(MediaType.APPLICATION_JSON).body(request)
                .retrieve().body(DatabaseOrder.class);
        } catch (RestClientResponseException exception) {
            throw translate(exception);
        }
    }

    public DatabaseOrder update(long id, OrderRequest request) {
        try {
            return restClient.put().uri("/internal/orders/{id}", id)
                .contentType(MediaType.APPLICATION_JSON).body(request)
                .retrieve().body(DatabaseOrder.class);
        } catch (RestClientResponseException exception) {
            throw translate(exception);
        }
    }

    public DatabaseOrder updateStatus(long id, StatusRequest request) {
        try {
            return restClient.patch().uri("/internal/orders/{id}/status", id)
                .contentType(MediaType.APPLICATION_JSON).body(request)
                .retrieve().body(DatabaseOrder.class);
        } catch (RestClientResponseException exception) {
            throw translate(exception);
        }
    }

    public void delete(long id) {
        try {
            restClient.delete().uri("/internal/orders/{id}", id).retrieve().toBodilessEntity();
        } catch (RestClientResponseException exception) {
            throw translate(exception);
        }
    }

    public List<DatabaseOrderLine> listLines(long orderId) {
        try {
            return restClient.get().uri("/internal/orders/{orderId}/lines", orderId)
                .retrieve().body(new ParameterizedTypeReference<>() {});
        } catch (RestClientResponseException exception) {
            throw translate(exception);
        }
    }

    public DatabaseOrderLine addLine(long orderId, OrderLineRequest request) {
        try {
            return restClient.post().uri("/internal/orders/{orderId}/lines", orderId)
                .contentType(MediaType.APPLICATION_JSON).body(request)
                .retrieve().body(DatabaseOrderLine.class);
        } catch (RestClientResponseException exception) {
            throw translate(exception);
        }
    }

    public DatabaseOrderLine updateLine(long orderId, long lineId, OrderLineRequest request) {
        try {
            return restClient.put().uri("/internal/orders/{orderId}/lines/{lineId}", orderId, lineId)
                .contentType(MediaType.APPLICATION_JSON).body(request)
                .retrieve().body(DatabaseOrderLine.class);
        } catch (RestClientResponseException exception) {
            throw translate(exception);
        }
    }

    public void deleteLine(long orderId, long lineId) {
        try {
            restClient.delete().uri("/internal/orders/{orderId}/lines/{lineId}", orderId, lineId)
                .retrieve().toBodilessEntity();
        } catch (RestClientResponseException exception) {
            throw translate(exception);
        }
    }

    private java.util.Optional<String> optionalText(String value) {
        return value == null || value.isBlank() ? java.util.Optional.empty() : java.util.Optional.of(value);
    }

    private ResponseStatusException translate(RestClientResponseException exception) {
        return new ResponseStatusException(
            exception.getStatusCode(),
            "Database API request failed: " + exception.getResponseBodyAsString(),
            exception
        );
    }
}
