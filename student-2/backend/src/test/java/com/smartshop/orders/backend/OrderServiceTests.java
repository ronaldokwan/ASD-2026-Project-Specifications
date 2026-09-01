package com.smartshop.orders.backend;

import com.smartshop.orders.backend.client.DatabaseApiClient;
import com.smartshop.orders.backend.dto.OrderModels.DatabaseCreateRequest;
import com.smartshop.orders.backend.dto.OrderModels.DatabaseOrder;
import com.smartshop.orders.backend.dto.OrderModels.DatabaseOrderLine;
import com.smartshop.orders.backend.dto.OrderModels.OrderLineRequest;
import com.smartshop.orders.backend.dto.OrderModels.OrderRequest;
import com.smartshop.orders.backend.dto.OrderModels.ProductInfo;
import com.smartshop.orders.backend.dto.OrderModels.StockCheckResult;
import com.smartshop.orders.backend.dto.OrderModels.StockUpdateResult;
import com.smartshop.orders.backend.service.OrderService;
import com.smartshop.orders.backend.service.ProductService;
import com.smartshop.orders.backend.service.StockService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.web.server.ResponseStatusException;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class OrderServiceTests {

    private DatabaseApiClient databaseApi;
    private ProductService productService;
    private StockService stockService;
    private OrderService orderService;

    @BeforeEach
    void setUp() {
        databaseApi = mock(DatabaseApiClient.class);
        productService = mock(ProductService.class);
        stockService = mock(StockService.class);
        orderService = new OrderService(databaseApi, productService, stockService);
    }

    @Test
    void checksAndDeductsStockWhenCreatingAnOrder() {
        OrderRequest request = new OrderRequest(
            "buyer@example.com", "pending",
            List.of(new OrderLineRequest(null, "SKU-1", 2, new BigDecimal("7.50")))
        );
        when(stockService.checkStock(any())).thenReturn(new StockCheckResult(true, "ok"));
        when(stockService.deductStock(anyString(), any())).thenReturn(new StockUpdateResult(true, "ok"));
        when(productService.getProductBySku("SKU-1"))
            .thenReturn(new ProductInfo("SKU-1", "Test product", new BigDecimal("7.50")));
        when(databaseApi.create(any(DatabaseCreateRequest.class))).thenAnswer(invocation -> {
            DatabaseCreateRequest create = invocation.getArgument(0);
            return new DatabaseOrder(
                1L, create.orderNumber(), create.customerEmail(), create.status(),
                LocalDateTime.now(), LocalDateTime.now(),
                List.of(new DatabaseOrderLine(2L, "SKU-1", 2, new BigDecimal("7.50"),
                    new BigDecimal("15.00"))),
                new BigDecimal("15.00")
            );
        });

        var created = orderService.create(request);

        assertThat(created.orderTotal()).isEqualByComparingTo("15.00");
        assertThat(created.lines().getFirst().productName()).isEqualTo("Test product");
        verify(stockService).checkStock(any());
        verify(stockService).deductStock(anyString(), any());
    }

    @Test
    void doesNotSaveWhenStockIsInsufficient() {
        OrderRequest request = new OrderRequest(
            "buyer@example.com", "pending",
            List.of(new OrderLineRequest(null, "SKU-1", 20, BigDecimal.ONE))
        );
        when(stockService.checkStock(any()))
            .thenReturn(new StockCheckResult(false, "Insufficient stock"));

        assertThatThrownBy(() -> orderService.create(request))
            .isInstanceOf(ResponseStatusException.class)
            .hasMessageContaining("Insufficient stock");
        verify(databaseApi, never()).create(any());
        verify(stockService, never()).deductStock(anyString(), any());
    }
}
