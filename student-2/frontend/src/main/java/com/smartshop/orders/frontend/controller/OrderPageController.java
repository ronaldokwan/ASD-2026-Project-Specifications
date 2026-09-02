package com.smartshop.orders.frontend.controller;

import com.smartshop.orders.frontend.client.BackendClient;
import com.smartshop.orders.frontend.dto.FrontendModels.AiResponse;
import com.smartshop.orders.frontend.dto.FrontendModels.OrderLineRequest;
import com.smartshop.orders.frontend.dto.FrontendModels.OrderLineResponse;
import com.smartshop.orders.frontend.dto.FrontendModels.OrderRequest;
import com.smartshop.orders.frontend.dto.FrontendModels.OrderResponse;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestParam;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

@Controller
public class OrderPageController {

    private final BackendClient backend;

    public OrderPageController(BackendClient backend) {
        this.backend = backend;
    }

    @GetMapping("/")
    public String home() {
        return "redirect:/orders";
    }

    @GetMapping("/orders")
    public String orders(
        @RequestParam(required = false) String status,
        @RequestParam(required = false) String customerEmail,
        @RequestParam(required = false) String orderNumber,
        Model model
    ) {
        populateOrders(model, status, customerEmail, orderNumber);
        return "orders";
    }

    @GetMapping("/orders/table")
    public String ordersTable(
        @RequestParam(required = false) String status,
        @RequestParam(required = false) String customerEmail,
        @RequestParam(required = false) String orderNumber,
        Model model
    ) {
        populateOrders(model, status, customerEmail, orderNumber);
        return "fragments/orders-table :: table";
    }

    @GetMapping("/orders/new")
    public String newOrder(Model model) {
        renderForm(model, null, "", "pending", List.of(blankLine()), null);
        return "order-form";
    }

    @PostMapping("/orders")
    public String create(
        @RequestParam String customerEmail,
        @RequestParam String status,
        @RequestParam(required = false) List<String> lineId,
        @RequestParam List<String> sku,
        @RequestParam List<Integer> quantity,
        @RequestParam List<BigDecimal> unitPrice,
        Model model
    ) {
        List<OrderLineRequest> lines = buildLines(lineId, sku, quantity, unitPrice);
        try {
            OrderResponse created = backend.create(new OrderRequest(customerEmail, status, lines));
            return "redirect:/orders/" + created.id() + "?created=true";
        } catch (RuntimeException exception) {
            renderForm(model, null, customerEmail, status, toDisplayLines(lines), readableError(exception));
            return "order-form";
        }
    }

    @GetMapping("/orders/{id}")
    public String detail(@PathVariable long id, Model model) {
        model.addAttribute("order", backend.get(id));
        return "order-detail";
    }

    @GetMapping("/orders/{id}/edit")
    public String edit(@PathVariable long id, Model model) {
        OrderResponse order = backend.get(id);
        renderForm(model, id, order.customerEmail(), order.status(), order.lines(), null);
        return "order-form";
    }

    @PostMapping("/orders/{id}")
    public String update(
        @PathVariable long id,
        @RequestParam String customerEmail,
        @RequestParam String status,
        @RequestParam(required = false) List<String> lineId,
        @RequestParam List<String> sku,
        @RequestParam List<Integer> quantity,
        @RequestParam List<BigDecimal> unitPrice,
        Model model
    ) {
        List<OrderLineRequest> lines = buildLines(lineId, sku, quantity, unitPrice);
        try {
            backend.update(id, new OrderRequest(customerEmail, status, lines));
            return "redirect:/orders/" + id + "?updated=true";
        } catch (RuntimeException exception) {
            renderForm(model, id, customerEmail, status, toDisplayLines(lines), readableError(exception));
            return "order-form";
        }
    }

    @PostMapping("/orders/{id}/status")
    public String updateStatus(@PathVariable long id, @RequestParam String status) {
        backend.updateStatus(id, status);
        return "redirect:/orders/" + id + "?updated=true";
    }

    @PostMapping("/orders/{id}/delete")
    public String delete(@PathVariable long id) {
        backend.delete(id);
        return "redirect:/orders?deleted=true";
    }

    @PostMapping("/orders/{id}/ai/delay-email")
    public String delayEmail(@PathVariable long id, Model model) {
        model.addAttribute("ai", backend.delayEmail(id));
        return "fragments/ai-result :: result";
    }

    @PostMapping("/orders/ai/customer-summary")
    public String customerSummary(@RequestParam String customerEmail, Model model) {
        model.addAttribute("ai", backend.customerSummary(customerEmail));
        return "fragments/ai-result :: result";
    }

    private void populateOrders(
        Model model,
        String status,
        String customerEmail,
        String orderNumber
    ) {
        model.addAttribute("orders", backend.list(status, customerEmail, orderNumber));
        model.addAttribute("selectedStatus", status == null ? "" : status);
        model.addAttribute("customerEmail", customerEmail == null ? "" : customerEmail);
        model.addAttribute("orderNumber", orderNumber == null ? "" : orderNumber);
    }

    private void renderForm(
        Model model,
        Long orderId,
        String customerEmail,
        String status,
        List<OrderLineResponse> lines,
        String error
    ) {
        model.addAttribute("editing", orderId != null);
        model.addAttribute("orderId", orderId);
        model.addAttribute("customerEmail", customerEmail);
        model.addAttribute("status", status);
        model.addAttribute("lines", lines);
        model.addAttribute("products", backend.listProducts());
        model.addAttribute("error", error);
    }

    private List<OrderLineRequest> buildLines(
        List<String> ids,
        List<String> skus,
        List<Integer> quantities,
        List<BigDecimal> unitPrices
    ) {
        if (skus.size() != quantities.size() || skus.size() != unitPrices.size()) {
            throw new IllegalArgumentException("Each order line must include SKU, quantity and price");
        }
        List<OrderLineRequest> lines = new ArrayList<>();
        for (int index = 0; index < skus.size(); index++) {
            Long id = ids != null && index < ids.size() && !ids.get(index).isBlank()
                ? Long.valueOf(ids.get(index)) : null;
            lines.add(new OrderLineRequest(id, skus.get(index), quantities.get(index), unitPrices.get(index)));
        }
        return lines;
    }

    private List<OrderLineResponse> toDisplayLines(List<OrderLineRequest> lines) {
        return lines.stream().map(line -> new OrderLineResponse(
            line.id(), line.sku(), "", line.quantity(), line.unitPrice(),
            line.unitPrice().multiply(BigDecimal.valueOf(line.quantity()))
        )).toList();
    }

    private OrderLineResponse blankLine() {
        return new OrderLineResponse(null, "", "", 1, BigDecimal.ZERO, BigDecimal.ZERO);
    }

    private String readableError(RuntimeException exception) {
        return exception.getMessage() == null ? "The request could not be completed" : exception.getMessage();
    }
}
