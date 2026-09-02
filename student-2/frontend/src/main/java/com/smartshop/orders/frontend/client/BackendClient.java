package com.smartshop.orders.frontend.client;

import com.smartshop.orders.frontend.dto.FrontendModels.AiResponse;
import com.smartshop.orders.frontend.dto.FrontendModels.CustomerSummaryRequest;
import com.smartshop.orders.frontend.dto.FrontendModels.OrderRequest;
import com.smartshop.orders.frontend.dto.FrontendModels.OrderResponse;
import com.smartshop.orders.frontend.dto.FrontendModels.ProductInfo;
import com.smartshop.orders.frontend.dto.FrontendModels.StatusRequest;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

import java.util.List;
import java.util.Optional;

@Component
public class BackendClient {

    private final RestClient restClient;

    public BackendClient(RestClient.Builder builder, @Value("${services.backend-url}") String backendUrl) {
        this.restClient = builder.baseUrl(backendUrl).build();
    }

    public List<OrderResponse> list(String status, String customerEmail, String orderNumber) {
        return restClient.get()
            .uri(uriBuilder -> uriBuilder.path("/api/orders")
                .queryParamIfPresent("status", optionalText(status))
                .queryParamIfPresent("customerEmail", optionalText(customerEmail))
                .queryParamIfPresent("orderNumber", optionalText(orderNumber))
                .build())
            .retrieve().body(new ParameterizedTypeReference<>() {});
    }

    public OrderResponse get(long id) {
        return restClient.get().uri("/api/orders/{id}", id)
            .retrieve().body(OrderResponse.class);
    }

    public OrderResponse create(OrderRequest request) {
        return restClient.post().uri("/api/orders")
            .contentType(MediaType.APPLICATION_JSON).body(request)
            .retrieve().body(OrderResponse.class);
    }

    public OrderResponse update(long id, OrderRequest request) {
        return restClient.put().uri("/api/orders/{id}", id)
            .contentType(MediaType.APPLICATION_JSON).body(request)
            .retrieve().body(OrderResponse.class);
    }

    public OrderResponse updateStatus(long id, String status) {
        return restClient.patch().uri("/api/orders/{id}/status", id)
            .contentType(MediaType.APPLICATION_JSON).body(new StatusRequest(status))
            .retrieve().body(OrderResponse.class);
    }

    public void delete(long id) {
        restClient.delete().uri("/api/orders/{id}", id).retrieve().toBodilessEntity();
    }

    public List<ProductInfo> listProducts() {
        return restClient.get().uri("/api/catalog/products")
            .retrieve().body(new ParameterizedTypeReference<>() {});
    }

    public AiResponse delayEmail(long id) {
        return restClient.post().uri("/api/orders/{id}/ai/delay-email", id)
            .retrieve().body(AiResponse.class);
    }

    public AiResponse customerSummary(String email) {
        return restClient.post().uri("/api/orders/ai/customer-summary")
            .contentType(MediaType.APPLICATION_JSON).body(new CustomerSummaryRequest(email))
            .retrieve().body(AiResponse.class);
    }

    private Optional<String> optionalText(String value) {
        return value == null || value.isBlank() ? Optional.empty() : Optional.of(value);
    }
}
