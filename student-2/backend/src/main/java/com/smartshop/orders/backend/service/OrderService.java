package com.smartshop.orders.backend.service;

import com.smartshop.orders.backend.client.DatabaseApiClient;
import com.smartshop.orders.backend.dto.OrderModels.DatabaseCreateRequest;
import com.smartshop.orders.backend.dto.OrderModels.DatabaseOrder;
import com.smartshop.orders.backend.dto.OrderModels.DatabaseOrderLine;
import com.smartshop.orders.backend.dto.OrderModels.OrderLineRequest;
import com.smartshop.orders.backend.dto.OrderModels.OrderLineResponse;
import com.smartshop.orders.backend.dto.OrderModels.OrderRequest;
import com.smartshop.orders.backend.dto.OrderModels.OrderResponse;
import com.smartshop.orders.backend.dto.OrderModels.ProductInfo;
import com.smartshop.orders.backend.dto.OrderModels.StatusRequest;
import com.smartshop.orders.backend.dto.OrderModels.StockCheckResult;
import com.smartshop.orders.backend.dto.OrderModels.StockItemRequest;
import com.smartshop.orders.backend.dto.OrderModels.StockUpdateResult;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.UUID;

@Service
public class OrderService {

    private final DatabaseApiClient databaseApi;
    private final ProductService productService;
    private final StockService stockService;

    public OrderService(
        DatabaseApiClient databaseApi,
        ProductService productService,
        StockService stockService
    ) {
        this.databaseApi = databaseApi;
        this.productService = productService;
        this.stockService = stockService;
    }

    public List<OrderResponse> list(String status, String customerEmail, String orderNumber) {
        return databaseApi.list(status, customerEmail, orderNumber).stream()
            .map(this::enrich)
            .toList();
    }

    public OrderResponse get(long id) {
        return enrich(databaseApi.get(id));
    }

    public OrderResponse create(OrderRequest request) {
        List<OrderLineRequest> confirmedLines = confirmProducts(request.lines());
        validateDistinctSkus(confirmedLines);
        List<StockItemRequest> items = toStockItems(confirmedLines);
        StockCheckResult stock = stockService.checkStock(items);
        if (!stock.sufficient()) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, stock.message());
        }

        String orderNumber = generateOrderNumber();
        DatabaseOrder created = databaseApi.create(new DatabaseCreateRequest(
            orderNumber, request.customerEmail(), request.status(), confirmedLines
        ));

        StockUpdateResult update = stockService.deductStock(orderNumber, items);
        if (!update.success()) {
            databaseApi.delete(created.id());
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, update.message());
        }
        return enrich(created);
    }

    public OrderResponse update(long id, OrderRequest request) {
        List<OrderLineRequest> confirmedLines = confirmProducts(request.lines());
        validateDistinctSkus(confirmedLines);
        return enrich(databaseApi.update(id, new OrderRequest(
            request.customerEmail(), request.status(), confirmedLines
        )));
    }

    public OrderResponse updateStatus(long id, StatusRequest request) {
        return enrich(databaseApi.updateStatus(id, request));
    }

    public void delete(long id) {
        databaseApi.delete(id);
    }

    public List<OrderLineResponse> listLines(long orderId) {
        return databaseApi.listLines(orderId).stream().map(this::enrichLine).toList();
    }

    public OrderLineResponse addLine(long orderId, OrderLineRequest request) {
        OrderLineRequest confirmedLine = confirmProduct(request);
        StockCheckResult stock = stockService.checkStock(toStockItems(List.of(confirmedLine)));
        if (!stock.sufficient()) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, stock.message());
        }
        return enrichLine(databaseApi.addLine(orderId, confirmedLine));
    }

    public OrderLineResponse updateLine(long orderId, long lineId, OrderLineRequest request) {
        return enrichLine(databaseApi.updateLine(orderId, lineId, confirmProduct(request)));
    }

    public void deleteLine(long orderId, long lineId) {
        databaseApi.deleteLine(orderId, lineId);
    }

    public StockCheckResult checkStock(List<OrderLineRequest> lines) {
        validateDistinctSkus(lines);
        return stockService.checkStock(toStockItems(lines));
    }

    private List<StockItemRequest> toStockItems(List<OrderLineRequest> lines) {
        return lines.stream()
            .map(line -> new StockItemRequest(line.sku().trim().toUpperCase(Locale.ROOT), line.quantity()))
            .toList();
    }

    private List<OrderLineRequest> confirmProducts(List<OrderLineRequest> lines) {
        return lines.stream().map(this::confirmProduct).toList();
    }

    private OrderLineRequest confirmProduct(OrderLineRequest line) {
        ProductInfo product = productService.requireProductBySku(line.sku());
        if (product.price() == null) {
            throw new ResponseStatusException(
                HttpStatus.SERVICE_UNAVAILABLE,
                "Product catalogue returned no price for SKU: " + product.sku()
            );
        }
        return new OrderLineRequest(line.id(), product.sku(), line.quantity(), product.price());
    }

    private void validateDistinctSkus(List<OrderLineRequest> lines) {
        Set<String> skus = new HashSet<>();
        for (OrderLineRequest line : lines) {
            String sku = line.sku().trim().toUpperCase(Locale.ROOT);
            if (!skus.add(sku)) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "Duplicate SKU in order: " + sku);
            }
        }
    }

    private String generateOrderNumber() {
        String timestamp = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss"));
        String random = UUID.randomUUID().toString().substring(0, 6).toUpperCase(Locale.ROOT);
        return "ORD-" + timestamp + "-" + random;
    }

    private OrderResponse enrich(DatabaseOrder order) {
        List<OrderLineResponse> lines = order.lines().stream().map(this::enrichLine).toList();
        int totalQuantity = lines.stream().mapToInt(OrderLineResponse::quantity).sum();
        BigDecimal total = lines.stream().map(OrderLineResponse::lineTotal)
            .reduce(BigDecimal.ZERO, BigDecimal::add);
        return new OrderResponse(
            order.id(), order.orderNumber(), order.customerEmail(), order.status(),
            order.orderedAt(), order.updatedAt(), lines, totalQuantity, total
        );
    }

    private OrderLineResponse enrichLine(DatabaseOrderLine line) {
        ProductInfo product = productService.getProductBySku(line.sku());
        BigDecimal lineTotal = line.unitPrice().multiply(BigDecimal.valueOf(line.quantity()));
        return new OrderLineResponse(
            line.id(), line.sku(), product.name(), line.quantity(), line.unitPrice(), lineTotal
        );
    }
}
