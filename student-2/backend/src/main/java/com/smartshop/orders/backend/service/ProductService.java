package com.smartshop.orders.backend.service;

import com.smartshop.orders.backend.dto.OrderModels.ProductInfo;
import com.smartshop.orders.backend.dto.OrderModels.ProductSearchResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

import java.math.BigDecimal;

@Service
public class ProductService {

    private final RestClient student1Client;

    public ProductService(
        RestClient.Builder builder,
        @Value("${services.product-api-url}") String productApiUrl
    ) {
        this.student1Client = builder.baseUrl(productApiUrl).build();
    }

    public ProductInfo getProductBySku(String sku) {
        String normalisedSku = normaliseSku(sku);

        try {
            ProductSearchResponse response = student1Client.get()
                .uri("/api/products?sku={sku}", normalisedSku)
                .retrieve()
                .body(ProductSearchResponse.class);

            if (response == null || response.products() == null || response.products().isEmpty()) {
                return fallbackProduct(normalisedSku);
            }

            return response.products().get(0);
        } catch (RestClientException exception) {
            return fallbackProduct(normalisedSku);
        }
    }

    private String normaliseSku(String sku) {
        return sku == null || sku.isBlank() ? "UNKNOWN" : sku.trim().toUpperCase();
    }

    private ProductInfo fallbackProduct(String sku) {
        return new ProductInfo(sku, sku, BigDecimal.ZERO);
    }
}
