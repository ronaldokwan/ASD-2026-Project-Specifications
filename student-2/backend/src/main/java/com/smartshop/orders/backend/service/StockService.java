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
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
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
        return adjustStock(orderNumber, items);
    }

    /**
     * Applies signed order quantity changes to Student 4 inventory.
     * Positive quantities consume stock; negative quantities return stock.
     */
    public StockUpdateResult adjustStock(String orderNumber, List<StockItemRequest> adjustments) {
        try {
            List<StockAdjustment> planned = new ArrayList<>();
            for (Map.Entry<String, Integer> entry : combineAdjustments(adjustments).entrySet()) {
                String sku = entry.getKey();
                int orderQuantityChange = entry.getValue();
                if (orderQuantityChange == 0) {
                    continue;
                }

                Optional<StockRecord> stock = findBySku(sku);
                if (stock.isEmpty()) {
                    return new StockUpdateResult(false, "No stock record exists for SKU " + sku);
                }

                long targetQuantity = (long) stock.get().quantity() - orderQuantityChange;
                if (targetQuantity < 0) {
                    return new StockUpdateResult(
                        false,
                        insufficientMessage(sku, stock.get().quantity(), orderQuantityChange)
                    );
                }
                if (targetQuantity > 999_999) {
                    return new StockUpdateResult(false, "Stock quantity exceeds the supported maximum for SKU " + sku);
                }
                planned.add(new StockAdjustment(stock.get(), (int) targetQuantity));
            }

            List<StockAdjustment> applied = new ArrayList<>();
            try {
                for (StockAdjustment adjustment : planned) {
                    updateQuantity(adjustment.stock().id(), adjustment.targetQuantity());
                    applied.add(adjustment);
                }
            } catch (RestClientException exception) {
                rollbackApplied(applied);
                return new StockUpdateResult(false, "Stock service could not update order " + orderNumber);
            }
            return new StockUpdateResult(true, "Stock updated successfully for order " + orderNumber);
        } catch (ResponseStatusException | RestClientException exception) {
            return new StockUpdateResult(false, "Stock service could not update order " + orderNumber);
        }
    }

    private Map<String, Integer> combineAdjustments(List<StockItemRequest> adjustments) {
        Map<String, Integer> combined = new LinkedHashMap<>();
        for (StockItemRequest adjustment : adjustments) {
            String sku = normaliseSku(adjustment.sku());
            combined.merge(sku, adjustment.quantity(), Math::addExact);
        }
        return combined;
    }

    private void updateQuantity(long stockId, int quantity) {
        stockClient.put()
            .uri("/api/stock/{id}", stockId)
            .contentType(MediaType.APPLICATION_JSON)
            .body(new StockQuantityUpdate(quantity))
            .retrieve()
            .toBodilessEntity();
    }

    private void rollbackApplied(List<StockAdjustment> applied) {
        for (int index = applied.size() - 1; index >= 0; index--) {
            StockAdjustment adjustment = applied.get(index);
            try {
                updateQuantity(adjustment.stock().id(), adjustment.stock().quantity());
            } catch (RestClientException ignored) {
                // Best-effort compensation; the caller still receives a failed update result.
            }
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

    private record StockAdjustment(StockRecord stock, int targetQuantity) {}
}
