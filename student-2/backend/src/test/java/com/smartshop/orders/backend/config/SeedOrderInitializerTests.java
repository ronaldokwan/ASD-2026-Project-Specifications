package com.smartshop.orders.backend.config;

import com.smartshop.orders.backend.client.DatabaseApiClient;
import com.smartshop.orders.backend.dto.OrderModels.DatabaseOrder;
import com.smartshop.orders.backend.dto.OrderModels.OrderRequest;
import com.smartshop.orders.backend.service.OrderService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class SeedOrderInitializerTests {

    private DatabaseApiClient databaseApi;
    private OrderService orderService;
    private SeedOrderInitializer initializer;

    @BeforeEach
    void setUp() {
        databaseApi = mock(DatabaseApiClient.class);
        orderService = mock(OrderService.class);
        initializer = new SeedOrderInitializer(databaseApi, orderService);
    }

    @Test
    void createsTenSeedOrdersThroughTheNormalOrderService() {
        when(databaseApi.list(null, null, null)).thenReturn(List.of());

        initializer.seedMissingOrders();

        ArgumentCaptor<OrderRequest> captor = ArgumentCaptor.forClass(OrderRequest.class);
        verify(orderService, times(10)).create(captor.capture());

        List<OrderRequest> requests = captor.getAllValues();
        assertThat(requests).extracting(OrderRequest::customerEmail)
            .containsExactly(
                "seed-order-001@example.com",
                "seed-order-002@example.com",
                "seed-order-003@example.com",
                "seed-order-004@example.com",
                "seed-order-005@example.com",
                "seed-order-006@example.com",
                "seed-order-007@example.com",
                "seed-order-008@example.com",
                "seed-order-009@example.com",
                "seed-order-010@example.com"
            );
        assertThat(requests).allSatisfy(request -> {
            assertThat(request.lines()).hasSize(1);
            assertThat(request.lines().getFirst().quantity()).isEqualTo(1);
        });
        assertThat(requests).extracting(request -> request.lines().getFirst().sku())
            .doesNotHaveDuplicates();
    }

    @Test
    void recreatesOnlyASeedOrderThatIsMissing() {
        List<DatabaseOrder> existing = java.util.stream.IntStream.rangeClosed(1, 9)
            .mapToObj(index -> existingSeed(index))
            .toList();
        when(databaseApi.list(null, null, null)).thenReturn(existing);

        initializer.seedMissingOrders();

        ArgumentCaptor<OrderRequest> captor = ArgumentCaptor.forClass(OrderRequest.class);
        verify(orderService).create(captor.capture());
        assertThat(captor.getValue().customerEmail()).isEqualTo("seed-order-010@example.com");
        assertThat(captor.getValue().lines().getFirst().sku()).isEqualTo("SKU-WEA-4001");
    }

    @Test
    void doesNotDuplicateSeedOrdersOnRestart() {
        List<DatabaseOrder> existing = java.util.stream.IntStream.rangeClosed(1, 10)
            .mapToObj(index -> existingSeed(index))
            .toList();
        when(databaseApi.list(null, null, null)).thenReturn(existing);

        initializer.seedMissingOrders();

        verify(orderService, never()).create(any(OrderRequest.class));
    }

    @Test
    void retriesAfterTheDatabaseBecomesAvailable() {
        when(databaseApi.list(null, null, null))
            .thenThrow(new RuntimeException("Database is starting"))
            .thenReturn(List.of());

        initializer.seedMissingOrders();
        verify(orderService, never()).create(any(OrderRequest.class));

        initializer.seedMissingOrders();
        verify(orderService, times(10)).create(any(OrderRequest.class));
    }

    @Test
    void continuesWhenOneSeedOrderCannotBeCreated() {
        when(databaseApi.list(null, null, null)).thenReturn(List.of());
        when(orderService.create(any(OrderRequest.class)))
            .thenThrow(new RuntimeException("Product service unavailable"))
            .thenReturn(null);

        assertThatCode(initializer::seedMissingOrders).doesNotThrowAnyException();
        verify(orderService, times(10)).create(any(OrderRequest.class));
    }

    private DatabaseOrder existingSeed(int index) {
        return new DatabaseOrder(
            (long) index,
            "ORD-SEED-" + index,
            "seed-order-%03d@example.com".formatted(index),
            "pending",
            null,
            null,
            List.of(),
            null
        );
    }
}
