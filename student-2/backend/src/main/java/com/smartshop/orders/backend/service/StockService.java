package com.smartshop.orders.backend.service;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.smartshop.orders.backend.dto.OrderModels.StockCheckResult;
import com.smartshop.orders.backend.dto.OrderModels.StockItemRequest;
import com.smartshop.orders.backend.dto.OrderModels.StockUpdateResult;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.server.ResponseStatusException;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Optional;

@Service
public class StockService {

    private final RestClient stockClient;

    public StockService(
        RestClient.Builder builder,
        @Value("${services.stock-api-url}") String stockApiUrl
    ) {
        this.stockClient = builder.baseUrl(stockApiUrl).build();
    }

    public StockCheckResult checkStock(List<StockItemRequest> items) {
        for (StockItemRequest item : items) {
            String sku = normaliseSku(item.sku());
            Optional<StockRecord> stock = findBySku(sku);
            if (stock.isEmpty()) {
                return new StockCheckResult(false, "No stock record exists for SKU " + sku);
            }
            if (stock.get().quantity() < item.quantity()) {
                return new StockCheckResult(false, insufficientMessage(sku, stock.get().quantity(), item.quantity()));
            }
        }
        return new StockCheckResult(true, "Stock is sufficient");
    }

    public StockUpdateResult deductStock(String orderNumber, List<StockItemRequest> items) {
        try {
            List<StockDeduction> deductions = new ArrayList<>();
            for (StockItemRequest item : items) {
                String sku = normaliseSku(item.sku());
                Optional<StockRecord> stock = findBySku(sku);
                if (stock.isEmpty()) {
                    return new StockUpdateResult(false, "No stock record exists for SKU " + sku);
                }
                if (stock.get().quantity() < item.quantity()) {
                    return new StockUpdateResult(
                        false,
                        insufficientMessage(sku, stock.get().quantity(), item.quantity())
                    );
                }
                deductions.add(new StockDeduction(stock.get(), item.quantity()));
            }

            for (StockDeduction deduction : deductions) {
                int remainingQuantity = deduction.stock().quantity() - deduction.requestedQuantity();
                stockClient.put()
                    .uri("/api/stock/{id}", deduction.stock().id())
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(new StockQuantityUpdate(remainingQuantity))
                    .retrieve()
                    .toBodilessEntity();
            }
            return new StockUpdateResult(true, "Stock updated successfully for order " + orderNumber);
        } catch (ResponseStatusException | RestClientException exception) {
            return new StockUpdateResult(false, "Stock service could not update order " + orderNumber);
        }
    }

    private Optional<StockRecord> findBySku(String sku) {
        try {
            StockSearchResponse response = stockClient.get()
                .uri("/api/stock?sku={sku}", sku)
                .retrieve()
                .body(StockSearchResponse.class);

            if (response == null || response.stock() == null || response.stock().isEmpty()) {
                return Optional.empty();
            }
            return response.stock().stream()
                .filter(stock -> sku.equalsIgnoreCase(stock.sku()))
                .findFirst();
        } catch (RestClientException exception) {
            throw new ResponseStatusException(
                HttpStatus.SERVICE_UNAVAILABLE,
                "Stock service is unavailable",
                exception
            );
        }
    }

    private String normaliseSku(String sku) {
        return sku == null ? "" : sku.trim().toUpperCase(Locale.ROOT);
    }

    private String insufficientMessage(String sku, int available, int requested) {
        return "Insufficient stock for SKU " + sku
            + " (available " + available + ", requested " + requested + ")";
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    private record StockSearchResponse(int count, List<StockRecord> stock) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    private record StockRecord(long id, String sku, int quantity) {}

    private record StockQuantityUpdate(int quantity) {}

    private record StockDeduction(StockRecord stock, int requestedQuantity) {}
}
