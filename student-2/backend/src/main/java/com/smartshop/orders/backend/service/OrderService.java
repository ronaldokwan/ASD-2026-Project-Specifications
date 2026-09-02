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
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.function.Supplier;

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
        DatabaseOrder existing = databaseApi.get(id);
        List<OrderLineRequest> confirmedLines = confirmProducts(request.lines());
        validateDistinctSkus(confirmedLines);
        List<StockItemRequest> adjustments = inventoryChanges(existing.lines(), confirmedLines);
        DatabaseOrder updated = withInventoryAdjustment(
            existing.orderNumber(),
            adjustments,
            () -> databaseApi.update(id, new OrderRequest(
                request.customerEmail(), request.status(), confirmedLines
            ))
        );
        return enrich(updated);
    }

    public OrderResponse updateStatus(long id, StatusRequest request) {
        return enrich(databaseApi.updateStatus(id, request));
    }

    public void delete(long id) {
        DatabaseOrder existing = databaseApi.get(id);
        List<StockItemRequest> returns = existing.lines().stream()
            .map(line -> new StockItemRequest(line.sku(), -line.quantity()))
            .toList();
        withInventoryAdjustment(existing.orderNumber(), returns, () -> {
            databaseApi.delete(id);
            return null;
        });
    }

    public List<OrderLineResponse> listLines(long orderId) {
        return databaseApi.listLines(orderId).stream().map(this::enrichLine).toList();
    }

    public OrderLineResponse addLine(long orderId, OrderLineRequest request) {
        DatabaseOrder existing = databaseApi.get(orderId);
        OrderLineRequest confirmedLine = confirmProduct(request);
        List<StockItemRequest> adjustment = toStockItems(List.of(confirmedLine));
        DatabaseOrderLine added = withInventoryAdjustment(
            existing.orderNumber(),
            adjustment,
            () -> databaseApi.addLine(orderId, confirmedLine)
        );
        return enrichLine(added);
    }

    public OrderLineResponse updateLine(long orderId, long lineId, OrderLineRequest request) {
        DatabaseOrder existing = databaseApi.get(orderId);
        DatabaseOrderLine existingLine = findLine(existing, lineId);
        OrderLineRequest confirmedLine = confirmProduct(request);
        List<StockItemRequest> adjustments = inventoryChanges(
            List.of(existingLine),
            List.of(confirmedLine)
        );
        DatabaseOrderLine updated = withInventoryAdjustment(
            existing.orderNumber(),
            adjustments,
            () -> databaseApi.updateLine(orderId, lineId, confirmedLine)
        );
        return enrichLine(updated);
    }

    public void deleteLine(long orderId, long lineId) {
        DatabaseOrder existing = databaseApi.get(orderId);
        DatabaseOrderLine existingLine = findLine(existing, lineId);
        List<StockItemRequest> returns = List.of(
            new StockItemRequest(existingLine.sku(), -existingLine.quantity())
        );
        withInventoryAdjustment(existing.orderNumber(), returns, () -> {
            databaseApi.deleteLine(orderId, lineId);
            return null;
        });
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

    private List<StockItemRequest> inventoryChanges(
        List<DatabaseOrderLine> existingLines,
        List<OrderLineRequest> replacementLines
    ) {
        Map<String, Integer> changes = new LinkedHashMap<>();
        existingLines.forEach(line -> changes.merge(
            normaliseSku(line.sku()), -line.quantity(), Math::addExact
        ));
        replacementLines.forEach(line -> changes.merge(
            normaliseSku(line.sku()), line.quantity(), Math::addExact
        ));

        List<StockItemRequest> result = new ArrayList<>();
        changes.forEach((sku, quantity) -> {
            if (quantity != 0) {
                result.add(new StockItemRequest(sku, quantity));
            }
        });
        return result;
    }

    private <T> T withInventoryAdjustment(
        String orderNumber,
        List<StockItemRequest> adjustments,
        Supplier<T> databaseOperation
    ) {
        List<StockItemRequest> effective = adjustments.stream()
            .filter(item -> item.quantity() != 0)
            .toList();
        if (effective.isEmpty()) {
            return databaseOperation.get();
        }

        List<StockItemRequest> requiredStock = effective.stream()
            .filter(item -> item.quantity() > 0)
            .toList();
        if (!requiredStock.isEmpty()) {
            StockCheckResult stock = stockService.checkStock(requiredStock);
            if (!stock.sufficient()) {
                throw new ResponseStatusException(HttpStatus.CONFLICT, stock.message());
            }
        }

        StockUpdateResult adjustment = stockService.adjustStock(orderNumber, effective);
        if (!adjustment.success()) {
            throw stockAdjustmentFailure(adjustment);
        }

        try {
            return databaseOperation.get();
        } catch (RuntimeException databaseFailure) {
            List<StockItemRequest> inverse = effective.stream()
                .map(item -> new StockItemRequest(item.sku(), -item.quantity()))
                .toList();
            StockUpdateResult rollback = stockService.adjustStock(orderNumber + " rollback", inverse);
            if (!rollback.success()) {
                throw new ResponseStatusException(
                    HttpStatus.BAD_GATEWAY,
                    "Order update failed and inventory rollback also failed",
                    databaseFailure
                );
            }
            throw databaseFailure;
        }
    }

    private ResponseStatusException stockAdjustmentFailure(StockUpdateResult result) {
        HttpStatus status = result.message().startsWith("Insufficient stock")
            ? HttpStatus.CONFLICT
            : HttpStatus.BAD_GATEWAY;
        return new ResponseStatusException(status, result.message());
    }

    private DatabaseOrderLine findLine(DatabaseOrder order, long lineId) {
        return order.lines().stream()
            .filter(line -> line.id() != null && line.id() == lineId)
            .findFirst()
            .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Order line not found"));
    }

    private String normaliseSku(String sku) {
        return sku == null ? "" : sku.trim().toUpperCase(Locale.ROOT);
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
