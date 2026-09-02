package com.smartshop.orders.backend.service;

import com.smartshop.orders.backend.dto.OrderModels.ProductInfo;
import com.smartshop.orders.backend.dto.OrderModels.ProductSearchResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.server.ResponseStatusException;

import java.math.BigDecimal;
import java.util.List;
import java.util.Locale;

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
            ProductInfo product = findProduct(normalisedSku);
            return product == null ? fallbackProduct(normalisedSku) : product;
        } catch (RestClientException exception) {
            return fallbackProduct(normalisedSku);
        }
    }

    public ProductInfo requireProductBySku(String sku) {
        String normalisedSku = normaliseSku(sku);

        try {
            ProductInfo product = findProduct(normalisedSku);
            if (product == null) {
                throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST,
                    "Unknown product SKU: " + normalisedSku
                );
            }
            return product;
        } catch (RestClientException exception) {
            throw new ResponseStatusException(
                HttpStatus.SERVICE_UNAVAILABLE,
                "Product catalogue is unavailable",
                exception
            );
        }
    }

    public List<ProductInfo> listProducts() {
        try {
            ProductSearchResponse response = student1Client.get()
                .uri("/api/products")
                .retrieve()
                .body(ProductSearchResponse.class);
            return response == null || response.products() == null
                ? List.of()
                : response.products();
        } catch (RestClientException exception) {
            throw new ResponseStatusException(
                HttpStatus.SERVICE_UNAVAILABLE,
                "Product catalogue is unavailable",
                exception
            );
        }
    }

    private ProductInfo findProduct(String normalisedSku) {
        ProductSearchResponse response = student1Client.get()
            .uri("/api/products?sku={sku}", normalisedSku)
            .retrieve()
            .body(ProductSearchResponse.class);
        return response == null || response.products() == null || response.products().isEmpty()
            ? null
            : response.products().get(0);
    }

    private String normaliseSku(String sku) {
        return sku == null || sku.isBlank() ? "UNKNOWN" : sku.trim().toUpperCase(Locale.ROOT);
    }

    private ProductInfo fallbackProduct(String sku) {
        return new ProductInfo(sku, sku, BigDecimal.ZERO);
    }
}
