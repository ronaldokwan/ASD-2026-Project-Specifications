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
import org.mockito.ArgumentCaptor;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
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
            List.of(new OrderLineRequest(null, "SKU-1", 2, new BigDecimal("0.01")))
        );
        when(stockService.checkStock(any())).thenReturn(new StockCheckResult(true, "ok"));
        when(stockService.deductStock(anyString(), any())).thenReturn(new StockUpdateResult(true, "ok"));
        when(productService.requireProductBySku("SKU-1"))
            .thenReturn(new ProductInfo("SKU-1", "Test product", new BigDecimal("7.50")));
        when(productService.getProductBySku("SKU-1"))
            .thenReturn(new ProductInfo("SKU-1", "Test product", new BigDecimal("7.50")));
        when(databaseApi.create(any(DatabaseCreateRequest.class))).thenAnswer(invocation -> {
            DatabaseCreateRequest create = invocation.getArgument(0);
            assertThat(create.lines().getFirst().unitPrice()).isEqualByComparingTo("7.50");
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
        when(productService.requireProductBySku("SKU-1"))
            .thenReturn(new ProductInfo("SKU-1", "Test product", BigDecimal.ONE));

        assertThatThrownBy(() -> orderService.create(request))
            .isInstanceOf(ResponseStatusException.class)
            .hasMessageContaining("Insufficient stock");
        verify(databaseApi, never()).create(any());
        verify(stockService, never()).deductStock(anyString(), any());
    }

    @Test
    void doesNotSaveAnUnknownProduct() {
        OrderRequest request = new OrderRequest(
            "buyer@example.com", "pending",
            List.of(new OrderLineRequest(null, "INVALID-SKU", 1, new BigDecimal("0.01")))
        );
        when(productService.requireProductBySku("INVALID-SKU"))
            .thenThrow(new ResponseStatusException(
                org.springframework.http.HttpStatus.BAD_REQUEST,
                "Unknown product SKU: INVALID-SKU"
            ));

        assertThatThrownBy(() -> orderService.create(request))
            .isInstanceOf(ResponseStatusException.class)
            .hasMessageContaining("Unknown product SKU: INVALID-SKU");

        verify(databaseApi, never()).create(any());
        verify(stockService, never()).checkStock(any());
        verify(stockService, never()).deductStock(anyString(), any());
    }

    @Test
    void reconcilesOnlyQuantityDifferencesWhenUpdatingAnOrder() {
        DatabaseOrder existing = order(
            List.of(
                line(10L, "SKU-1", 2, "7.50"),
                line(11L, "SKU-2", 5, "4.00")
            )
        );
        OrderRequest request = new OrderRequest(
            "buyer@example.com", "pending",
            List.of(
                new OrderLineRequest(10L, "SKU-1", 6, BigDecimal.ZERO),
                new OrderLineRequest(11L, "SKU-2", 2, BigDecimal.ZERO)
            )
        );
        when(databaseApi.get(1L)).thenReturn(existing);
        mockProduct("SKU-1", "7.50");
        mockProduct("SKU-2", "4.00");
        when(stockService.checkStock(any())).thenReturn(new StockCheckResult(true, "ok"));
        when(stockService.adjustStock(anyString(), any())).thenReturn(new StockUpdateResult(true, "ok"));
        when(databaseApi.update(eq(1L), any())).thenReturn(order(
            List.of(
                line(10L, "SKU-1", 6, "7.50"),
                line(11L, "SKU-2", 2, "4.00")
            )
        ));

        orderService.update(1L, request);

        @SuppressWarnings("unchecked")
        ArgumentCaptor<List<com.smartshop.orders.backend.dto.OrderModels.StockItemRequest>> checkCaptor =
            ArgumentCaptor.forClass(List.class);
        @SuppressWarnings("unchecked")
        ArgumentCaptor<List<com.smartshop.orders.backend.dto.OrderModels.StockItemRequest>> adjustmentCaptor =
            ArgumentCaptor.forClass(List.class);
        verify(stockService).checkStock(checkCaptor.capture());
        verify(stockService).adjustStock(eq("ORD-1"), adjustmentCaptor.capture());
        assertThat(checkCaptor.getValue())
            .extracting(item -> item.sku() + ":" + item.quantity())
            .containsExactly("SKU-1:4");
        assertThat(adjustmentCaptor.getValue())
            .extracting(item -> item.sku() + ":" + item.quantity())
            .containsExactly("SKU-1:4", "SKU-2:-3");
    }

    @Test
    void rollsInventoryBackWhenOrderUpdateFails() {
        when(databaseApi.get(1L)).thenReturn(order(List.of(line(10L, "SKU-1", 2, "7.50"))));
        mockProduct("SKU-1", "7.50");
        when(stockService.checkStock(any())).thenReturn(new StockCheckResult(true, "ok"));
        when(stockService.adjustStock(anyString(), any()))
            .thenReturn(new StockUpdateResult(true, "adjusted"))
            .thenReturn(new StockUpdateResult(true, "rolled back"));
        doThrow(new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Database unavailable"))
            .when(databaseApi).update(eq(1L), any());

        OrderRequest request = new OrderRequest(
            "buyer@example.com", "pending",
            List.of(new OrderLineRequest(10L, "SKU-1", 5, BigDecimal.ZERO))
        );

        assertThatThrownBy(() -> orderService.update(1L, request))
            .isInstanceOf(ResponseStatusException.class)
            .hasMessageContaining("Database unavailable");

        @SuppressWarnings("unchecked")
        ArgumentCaptor<List<com.smartshop.orders.backend.dto.OrderModels.StockItemRequest>> captor =
            ArgumentCaptor.forClass(List.class);
        verify(stockService, times(2)).adjustStock(anyString(), captor.capture());
        assertThat(captor.getAllValues().get(0).getFirst().quantity()).isEqualTo(3);
        assertThat(captor.getAllValues().get(1).getFirst().quantity()).isEqualTo(-3);
    }

    @Test
    void checksAndConsumesInventoryWhenAddingAnOrderLine() {
        when(databaseApi.get(1L)).thenReturn(order(List.of(line(10L, "SKU-1", 1, "7.50"))));
        mockProduct("SKU-2", "4.00");
        when(stockService.checkStock(any())).thenReturn(new StockCheckResult(true, "ok"));
        when(stockService.adjustStock(anyString(), any())).thenReturn(new StockUpdateResult(true, "ok"));
        when(databaseApi.addLine(eq(1L), any())).thenReturn(line(11L, "SKU-2", 2, "4.00"));

        orderService.addLine(1L, new OrderLineRequest(null, "SKU-2", 2, BigDecimal.ZERO));

        verify(stockService).checkStock(any());
        verify(stockService).adjustStock(eq("ORD-1"), any());
    }

    @Test
    void reconcilesInventoryWhenUpdatingOneOrderLine() {
        when(databaseApi.get(1L)).thenReturn(order(List.of(line(10L, "SKU-1", 2, "7.50"))));
        mockProduct("SKU-1", "7.50");
        when(stockService.checkStock(any())).thenReturn(new StockCheckResult(true, "ok"));
        when(stockService.adjustStock(anyString(), any())).thenReturn(new StockUpdateResult(true, "ok"));
        when(databaseApi.updateLine(eq(1L), eq(10L), any()))
            .thenReturn(line(10L, "SKU-1", 5, "7.50"));

        orderService.updateLine(
            1L,
            10L,
            new OrderLineRequest(10L, "SKU-1", 5, BigDecimal.ZERO)
        );

        @SuppressWarnings("unchecked")
        ArgumentCaptor<List<com.smartshop.orders.backend.dto.OrderModels.StockItemRequest>> captor =
            ArgumentCaptor.forClass(List.class);
        verify(stockService).adjustStock(eq("ORD-1"), captor.capture());
        assertThat(captor.getValue().getFirst().sku()).isEqualTo("SKU-1");
        assertThat(captor.getValue().getFirst().quantity()).isEqualTo(3);
    }

    @Test
    void returnsInventoryWhenDeletingAnOrderLine() {
        when(databaseApi.get(1L)).thenReturn(order(List.of(
            line(10L, "SKU-1", 3, "7.50"),
            line(11L, "SKU-2", 1, "4.00")
        )));
        when(stockService.adjustStock(anyString(), any())).thenReturn(new StockUpdateResult(true, "ok"));

        orderService.deleteLine(1L, 10L);

        @SuppressWarnings("unchecked")
        ArgumentCaptor<List<com.smartshop.orders.backend.dto.OrderModels.StockItemRequest>> captor =
            ArgumentCaptor.forClass(List.class);
        verify(stockService).adjustStock(eq("ORD-1"), captor.capture());
        assertThat(captor.getValue().getFirst().sku()).isEqualTo("SKU-1");
        assertThat(captor.getValue().getFirst().quantity()).isEqualTo(-3);
        verify(databaseApi).deleteLine(1L, 10L);
        verify(stockService, never()).checkStock(any());
    }

    @Test
    void returnsAllInventoryWhenDeletingAnOrder() {
        when(databaseApi.get(1L)).thenReturn(order(List.of(
            line(10L, "SKU-1", 3, "7.50"),
            line(11L, "SKU-2", 2, "4.00")
        )));
        when(stockService.adjustStock(anyString(), any())).thenReturn(new StockUpdateResult(true, "ok"));

        orderService.delete(1L);

        @SuppressWarnings("unchecked")
        ArgumentCaptor<List<com.smartshop.orders.backend.dto.OrderModels.StockItemRequest>> captor =
            ArgumentCaptor.forClass(List.class);
        verify(stockService).adjustStock(eq("ORD-1"), captor.capture());
        assertThat(captor.getValue())
            .extracting(item -> item.sku() + ":" + item.quantity())
            .containsExactly("SKU-1:-3", "SKU-2:-2");
        verify(databaseApi).delete(1L);
    }

    private DatabaseOrder order(List<DatabaseOrderLine> lines) {
        return new DatabaseOrder(
            1L, "ORD-1", "buyer@example.com", "pending",
            LocalDateTime.now(), LocalDateTime.now(), lines, BigDecimal.ZERO
        );
    }

    private DatabaseOrderLine line(long id, String sku, int quantity, String price) {
        BigDecimal unitPrice = new BigDecimal(price);
        return new DatabaseOrderLine(
            id, sku, quantity, unitPrice, unitPrice.multiply(BigDecimal.valueOf(quantity))
        );
    }

    private void mockProduct(String sku, String price) {
        ProductInfo product = new ProductInfo(sku, "Product " + sku, new BigDecimal(price));
        when(productService.requireProductBySku(sku)).thenReturn(product);
        when(productService.getProductBySku(sku)).thenReturn(product);
    }
}
