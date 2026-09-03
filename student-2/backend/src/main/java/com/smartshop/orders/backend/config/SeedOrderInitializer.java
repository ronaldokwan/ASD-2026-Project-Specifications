package com.smartshop.orders.backend.config;

import com.smartshop.orders.backend.client.DatabaseApiClient;
import com.smartshop.orders.backend.dto.OrderModels.DatabaseOrder;
import com.smartshop.orders.backend.dto.OrderModels.OrderLineRequest;
import com.smartshop.orders.backend.dto.OrderModels.OrderRequest;
import com.smartshop.orders.backend.service.OrderService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

@Component
@ConditionalOnProperty(name = "app.seed-orders", havingValue = "true", matchIfMissing = true)
public class SeedOrderInitializer {

    private static final Logger logger = LoggerFactory.getLogger(SeedOrderInitializer.class);

    private static final List<SeedOrder> SEED_ORDERS = List.of(
        new SeedOrder("seed-order-001@example.com", "pending", "SKU-AUD-1002"),
        new SeedOrder("seed-order-002@example.com", "shipped", "SKU-AUD-1003"),
        new SeedOrder("seed-order-003@example.com", "delivered", "SKU-COM-2001"),
        new SeedOrder("seed-order-004@example.com", "pending", "SKU-COM-2002"),
        new SeedOrder("seed-order-005@example.com", "shipped", "SKU-COM-2003"),
        new SeedOrder("seed-order-006@example.com", "delivered", "SKU-COM-2004"),
        new SeedOrder("seed-order-007@example.com", "pending", "SKU-HOM-3001"),
        new SeedOrder("seed-order-008@example.com", "shipped", "SKU-HOM-3002"),
        new SeedOrder("seed-order-009@example.com", "delivered", "SKU-HOM-3003"),
        new SeedOrder("seed-order-010@example.com", "pending", "SKU-WEA-4001")
    );

    private final DatabaseApiClient databaseApi;
    private final OrderService orderService;
    private volatile boolean seedingComplete;

    public SeedOrderInitializer(DatabaseApiClient databaseApi, OrderService orderService) {
        this.databaseApi = databaseApi;
        this.orderService = orderService;
    }

    @Scheduled(
        initialDelayString = "${app.seed-orders-initial-delay-ms:2000}",
        fixedDelayString = "${app.seed-orders-retry-ms:5000}"
    )
    public void seedMissingOrders() {
        if (seedingComplete) {
            return;
        }

        Set<String> existingEmails;
        try {
            List<DatabaseOrder> existingOrders = databaseApi.list(null, null, null);
            existingEmails = new HashSet<>(existingOrders.stream()
                .map(DatabaseOrder::customerEmail)
                .toList());
        } catch (RuntimeException exception) {
            logger.warn("Seed orders were not created because existing orders could not be read: {}",
                exception.getMessage());
            return;
        }

        for (SeedOrder seed : SEED_ORDERS) {
            if (existingEmails.contains(seed.customerEmail())) {
                continue;
            }

            try {
                orderService.create(new OrderRequest(
                    seed.customerEmail(),
                    seed.status(),
                    List.of(new OrderLineRequest(null, seed.sku(), 1, BigDecimal.ZERO))
                ));
                existingEmails.add(seed.customerEmail());
                logger.info("Created seed order for {}", seed.customerEmail());
            } catch (RuntimeException exception) {
                logger.warn("Could not create seed order for {}: {}",
                    seed.customerEmail(), exception.getMessage());
            }
        }

        if (SEED_ORDERS.stream().allMatch(seed -> existingEmails.contains(seed.customerEmail()))) {
            seedingComplete = true;
            logger.info("All {} seed orders are available", SEED_ORDERS.size());
        }
    }

    private record SeedOrder(String customerEmail, String status, String sku) {}
}
