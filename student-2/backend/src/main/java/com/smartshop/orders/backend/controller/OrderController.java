package com.smartshop.orders.backend.controller;

import com.smartshop.orders.backend.dto.OrderModels.OrderRequest;
import com.smartshop.orders.backend.dto.OrderModels.OrderResponse;
import com.smartshop.orders.backend.dto.OrderModels.OrderLineRequest;
import com.smartshop.orders.backend.dto.OrderModels.OrderLineResponse;
import com.smartshop.orders.backend.dto.OrderModels.ProductInfo;
import com.smartshop.orders.backend.dto.OrderModels.StatusRequest;
import com.smartshop.orders.backend.dto.OrderModels.StockCheckRequest;
import com.smartshop.orders.backend.dto.OrderModels.StockCheckResult;
import com.smartshop.orders.backend.service.OrderService;
import com.smartshop.orders.backend.service.ProductService;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api")
public class OrderController {

    private final OrderService orderService;
    private final ProductService productService;

    public OrderController(OrderService orderService, ProductService productService) {
        this.orderService = orderService;
        this.productService = productService;
    }

    @GetMapping("/orders")
    public List<OrderResponse> list(
        @RequestParam(required = false) String status,
        @RequestParam(required = false) String customerEmail,
        @RequestParam(required = false) String orderNumber
    ) {
        return orderService.list(status, customerEmail, orderNumber);
    }

    @GetMapping("/orders/{id}")
    public OrderResponse get(@PathVariable long id) {
        return orderService.get(id);
    }

    @PostMapping("/orders")
    public ResponseEntity<OrderResponse> create(@Valid @RequestBody OrderRequest request) {
        return ResponseEntity.status(HttpStatus.CREATED).body(orderService.create(request));
    }

    @PutMapping("/orders/{id}")
    public OrderResponse update(@PathVariable long id, @Valid @RequestBody OrderRequest request) {
        return orderService.update(id, request);
    }

    @PatchMapping("/orders/{id}/status")
    public OrderResponse updateStatus(
        @PathVariable long id,
        @Valid @RequestBody StatusRequest request
    ) {
        return orderService.updateStatus(id, request);
    }

    @DeleteMapping("/orders/{id}")
    public ResponseEntity<Void> delete(@PathVariable long id) {
        orderService.delete(id);
        return ResponseEntity.noContent().build();
    }

    @GetMapping("/orders/{orderId}/lines")
    public List<OrderLineResponse> listLines(@PathVariable long orderId) {
        return orderService.listLines(orderId);
    }

    @PostMapping("/orders/{orderId}/lines")
    public ResponseEntity<OrderLineResponse> addLine(
        @PathVariable long orderId,
        @Valid @RequestBody OrderLineRequest request
    ) {
        return ResponseEntity.status(HttpStatus.CREATED).body(orderService.addLine(orderId, request));
    }

    @PutMapping("/orders/{orderId}/lines/{lineId}")
    public OrderLineResponse updateLine(
        @PathVariable long orderId,
        @PathVariable long lineId,
        @Valid @RequestBody OrderLineRequest request
    ) {
        return orderService.updateLine(orderId, lineId, request);
    }

    @DeleteMapping("/orders/{orderId}/lines/{lineId}")
    public ResponseEntity<Void> deleteLine(@PathVariable long orderId, @PathVariable long lineId) {
        orderService.deleteLine(orderId, lineId);
        return ResponseEntity.noContent().build();
    }

    @PostMapping("/orders/stock-check")
    public StockCheckResult checkStock(@Valid @RequestBody StockCheckRequest request) {
        return orderService.checkStock(request.lines());
    }

    @GetMapping("/catalog/products")
    public ProductInfo product(@RequestParam String sku) {
        return productService.getProductBySku(sku);
    }
}
