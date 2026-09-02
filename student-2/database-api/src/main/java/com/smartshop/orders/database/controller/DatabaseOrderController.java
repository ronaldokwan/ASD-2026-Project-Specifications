package com.smartshop.orders.database.controller;

import com.smartshop.orders.database.dto.OrderPayloads.OrderLineResponse;
import com.smartshop.orders.database.dto.OrderPayloads.OrderLineWriteRequest;
import com.smartshop.orders.database.dto.OrderPayloads.OrderResponse;
import com.smartshop.orders.database.dto.OrderPayloads.OrderUpdateRequest;
import com.smartshop.orders.database.dto.OrderPayloads.OrderWriteRequest;
import com.smartshop.orders.database.dto.OrderPayloads.StatusUpdateRequest;
import com.smartshop.orders.database.service.DatabaseOrderService;
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
@RequestMapping("/internal/orders")
public class DatabaseOrderController {

    private final DatabaseOrderService orderService;

    public DatabaseOrderController(DatabaseOrderService orderService) {
        this.orderService = orderService;
    }

    @GetMapping
    public List<OrderResponse> list(
        @RequestParam(required = false) String status,
        @RequestParam(required = false) String customerEmail,
        @RequestParam(required = false) String orderNumber
    ) {
        return orderService.list(status, customerEmail, orderNumber);
    }

    @GetMapping("/{id}")
    public OrderResponse get(@PathVariable long id) {
        return orderService.get(id);
    }

    @PostMapping
    public ResponseEntity<OrderResponse> create(@Valid @RequestBody OrderWriteRequest request) {
        return ResponseEntity.status(HttpStatus.CREATED).body(orderService.create(request));
    }

    @PutMapping("/{id}")
    public OrderResponse update(
        @PathVariable long id,
        @Valid @RequestBody OrderUpdateRequest request
    ) {
        return orderService.update(id, request);
    }

    @PatchMapping("/{id}/status")
    public OrderResponse updateStatus(
        @PathVariable long id,
        @Valid @RequestBody StatusUpdateRequest request
    ) {
        return orderService.updateStatus(id, request.status());
    }

    @DeleteMapping("/{id}")
    public ResponseEntity<Void> delete(@PathVariable long id) {
        orderService.delete(id);
        return ResponseEntity.noContent().build();
    }

    @GetMapping("/{orderId}/lines")
    public List<OrderLineResponse> listLines(@PathVariable long orderId) {
        return orderService.listLines(orderId);
    }

    @PostMapping("/{orderId}/lines")
    public ResponseEntity<OrderLineResponse> addLine(
        @PathVariable long orderId,
        @Valid @RequestBody OrderLineWriteRequest request
    ) {
        return ResponseEntity.status(HttpStatus.CREATED).body(orderService.addLine(orderId, request));
    }

    @PutMapping("/{orderId}/lines/{lineId}")
    public OrderLineResponse updateLine(
        @PathVariable long orderId,
        @PathVariable long lineId,
        @Valid @RequestBody OrderLineWriteRequest request
    ) {
        return orderService.updateLine(orderId, lineId, request);
    }

    @DeleteMapping("/{orderId}/lines/{lineId}")
    public ResponseEntity<Void> deleteLine(@PathVariable long orderId, @PathVariable long lineId) {
        orderService.deleteLine(orderId, lineId);
        return ResponseEntity.noContent().build();
    }
}
