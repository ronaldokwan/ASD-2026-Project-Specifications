package com.smartshop.orders.backend.controller;

import com.smartshop.orders.backend.dto.MultiAgentModels.ReviewRequest;
import com.smartshop.orders.backend.dto.MultiAgentModels.StartWorkflowResponse;
import com.smartshop.orders.backend.dto.MultiAgentModels.WorkflowHistoryResponse;
import com.smartshop.orders.backend.dto.MultiAgentModels.WorkflowResponse;
import com.smartshop.orders.backend.service.OrderMultiAgentService;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/orders/{orderId}/multi-agent")
public class OrderMultiAgentController {

    private final OrderMultiAgentService service;

    public OrderMultiAgentController(OrderMultiAgentService service) {
        this.service = service;
    }

    @PostMapping
    @ResponseStatus(HttpStatus.ACCEPTED)
    public StartWorkflowResponse start(@PathVariable long orderId) {
        return service.start(orderId);
    }

    @GetMapping("/history")
    public WorkflowHistoryResponse history(@PathVariable long orderId) {
        return service.history(orderId);
    }

    @GetMapping("/{workflowId}")
    public WorkflowResponse status(
        @PathVariable long orderId,
        @PathVariable String workflowId
    ) {
        return service.get(orderId, workflowId);
    }

    @PostMapping("/{workflowId}/review")
    public WorkflowResponse review(
        @PathVariable long orderId,
        @PathVariable String workflowId,
        @Valid @RequestBody ReviewRequest request
    ) {
        return service.review(orderId, workflowId, request);
    }
}
