package com.smartshop.orders.database.service;

import com.smartshop.orders.database.dto.OrderPayloads.OrderLineResponse;
import com.smartshop.orders.database.dto.OrderPayloads.OrderLineWriteRequest;
import com.smartshop.orders.database.dto.OrderPayloads.OrderResponse;
import com.smartshop.orders.database.dto.OrderPayloads.OrderUpdateRequest;
import com.smartshop.orders.database.dto.OrderPayloads.OrderWriteRequest;
import com.smartshop.orders.database.entity.OrderEntity;
import com.smartshop.orders.database.entity.OrderLineEntity;
import com.smartshop.orders.database.repository.OrderLineRepository;
import com.smartshop.orders.database.repository.OrderRepository;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

@Service
public class DatabaseOrderService {

    private final OrderRepository orderRepository;
    private final OrderLineRepository lineRepository;

    public DatabaseOrderService(OrderRepository orderRepository, OrderLineRepository lineRepository) {
        this.orderRepository = orderRepository;
        this.lineRepository = lineRepository;
    }

    @Transactional(readOnly = true)
    public List<OrderResponse> list(String status, String customerEmail, String orderNumber) {
        return orderRepository.findAllByOrderByOrderedAtDesc().stream()
            .filter(order -> status == null || status.isBlank()
                || order.getStatus().equalsIgnoreCase(status))
            .filter(order -> customerEmail == null || customerEmail.isBlank()
                || order.getCustomerEmail().toLowerCase(Locale.ROOT)
                    .contains(customerEmail.toLowerCase(Locale.ROOT)))
            .filter(order -> orderNumber == null || orderNumber.isBlank()
                || order.getOrderNumber().toLowerCase(Locale.ROOT)
                    .contains(orderNumber.toLowerCase(Locale.ROOT)))
            .map(this::toResponse)
            .toList();
    }

    @Transactional(readOnly = true)
    public OrderResponse get(long id) {
        return toResponse(findOrder(id));
    }

    @Transactional
    public OrderResponse create(OrderWriteRequest request) {
        validateUniqueSkus(request.lines());
        if (orderRepository.existsByOrderNumber(request.orderNumber())) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Order number already exists");
        }

        OrderEntity order = new OrderEntity();
        order.setOrderNumber(request.orderNumber().trim());
        order.setCustomerEmail(request.customerEmail().trim().toLowerCase(Locale.ROOT));
        order.setStatus(request.status());
        request.lines().stream().map(this::newLine).forEach(order::addLine);
        return toResponse(orderRepository.save(order));
    }

    @Transactional
    public OrderResponse update(long id, OrderUpdateRequest request) {
        validateUniqueSkus(request.lines());
        OrderEntity order = findOrder(id);
        order.setCustomerEmail(request.customerEmail().trim().toLowerCase(Locale.ROOT));
        order.setStatus(request.status());
        synchroniseLines(order, request.lines());
        return toResponse(orderRepository.save(order));
    }

    @Transactional
    public OrderResponse updateStatus(long id, String status) {
        OrderEntity order = findOrder(id);
        order.setStatus(status);
        return toResponse(orderRepository.save(order));
    }

    @Transactional
    public void delete(long id) {
        OrderEntity order = findOrder(id);
        orderRepository.delete(order);
    }

    @Transactional(readOnly = true)
    public List<OrderLineResponse> listLines(long orderId) {
        return findOrder(orderId).getLines().stream().map(this::toLineResponse).toList();
    }

    @Transactional
    public OrderLineResponse addLine(long orderId, OrderLineWriteRequest request) {
        OrderEntity order = findOrder(orderId);
        ensureSkuNotUsed(order, request.sku(), null);
        OrderLineEntity line = newLine(request);
        order.addLine(line);
        orderRepository.save(order);
        return toLineResponse(line);
    }

    @Transactional
    public OrderLineResponse updateLine(long orderId, long lineId, OrderLineWriteRequest request) {
        OrderEntity order = findOrder(orderId);
        OrderLineEntity line = findLineInOrder(order, lineId);
        ensureSkuNotUsed(order, request.sku(), lineId);
        applyLine(line, request);
        return toLineResponse(lineRepository.save(line));
    }

    @Transactional
    public void deleteLine(long orderId, long lineId) {
        OrderEntity order = findOrder(orderId);
        if (order.getLines().size() == 1) {
            throw new ResponseStatusException(HttpStatus.CONFLICT,
                "An order must contain at least one line");
        }
        OrderLineEntity line = findLineInOrder(order, lineId);
        order.removeLine(line);
        orderRepository.save(order);
    }

    private OrderEntity findOrder(long id) {
        return orderRepository.findById(id)
            .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Order not found"));
    }

    private OrderLineEntity findLineInOrder(OrderEntity order, long lineId) {
        return order.getLines().stream()
            .filter(line -> line.getId().equals(lineId))
            .findFirst()
            .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "Order line not found"));
    }

    private void synchroniseLines(OrderEntity order, List<OrderLineWriteRequest> requests) {
        Map<Long, OrderLineEntity> existing = new HashMap<>();
        order.getLines().stream()
            .filter(line -> line.getId() != null)
            .forEach(line -> existing.put(line.getId(), line));

        Set<Long> retainedIds = new HashSet<>();
        List<OrderLineEntity> additions = new ArrayList<>();
        for (OrderLineWriteRequest request : requests) {
            if (request.id() != null && existing.containsKey(request.id())) {
                OrderLineEntity line = existing.get(request.id());
                applyLine(line, request);
                retainedIds.add(request.id());
            } else {
                additions.add(newLine(request));
            }
        }

        order.getLines().removeIf(line -> line.getId() != null && !retainedIds.contains(line.getId()));
        additions.forEach(order::addLine);
    }

    private OrderLineEntity newLine(OrderLineWriteRequest request) {
        OrderLineEntity line = new OrderLineEntity();
        applyLine(line, request);
        return line;
    }

    private void applyLine(OrderLineEntity line, OrderLineWriteRequest request) {
        line.setSku(request.sku().trim().toUpperCase(Locale.ROOT));
        line.setQuantity(request.quantity());
        line.setUnitPrice(request.unitPrice());
    }

    private void validateUniqueSkus(List<OrderLineWriteRequest> lines) {
        Set<String> skus = new HashSet<>();
        for (OrderLineWriteRequest line : lines) {
            String normalised = line.sku().trim().toUpperCase(Locale.ROOT);
            if (!skus.add(normalised)) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "Duplicate SKU in order: " + normalised);
            }
        }
    }

    private void ensureSkuNotUsed(OrderEntity order, String sku, Long excludedLineId) {
        boolean exists = order.getLines().stream().anyMatch(line ->
            (excludedLineId == null || !line.getId().equals(excludedLineId))
                && line.getSku().equalsIgnoreCase(sku.trim()));
        if (exists) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Duplicate SKU in order");
        }
    }

    private OrderResponse toResponse(OrderEntity order) {
        List<OrderLineResponse> lines = order.getLines().stream()
            .map(this::toLineResponse)
            .toList();
        BigDecimal total = lines.stream()
            .map(OrderLineResponse::lineTotal)
            .reduce(BigDecimal.ZERO, BigDecimal::add);
        return new OrderResponse(
            order.getId(), order.getOrderNumber(), order.getCustomerEmail(), order.getStatus(),
            order.getOrderedAt(), order.getUpdatedAt(), lines, total
        );
    }

    private OrderLineResponse toLineResponse(OrderLineEntity line) {
        BigDecimal total = line.getUnitPrice().multiply(BigDecimal.valueOf(line.getQuantity()));
        return new OrderLineResponse(
            line.getId(), line.getSku(), line.getQuantity(), line.getUnitPrice(), total
        );
    }
}
