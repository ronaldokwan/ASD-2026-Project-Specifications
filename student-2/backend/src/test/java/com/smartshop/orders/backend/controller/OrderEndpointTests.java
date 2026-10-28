package com.smartshop.orders.backend.controller;

import com.smartshop.orders.backend.dto.OrderModels.OrderLineResponse;
import com.smartshop.orders.backend.dto.OrderModels.OrderResponse;
import com.smartshop.orders.backend.dto.OrderModels.StatusRequest;
import com.smartshop.orders.backend.exception.ApiExceptionHandler;
import com.smartshop.orders.backend.service.OrderService;
import com.smartshop.orders.backend.service.ProductService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Release 2 post-commit evidence for two Student 2 backend endpoint functions.
 */
class OrderEndpointTests {

    private OrderService orderService;
    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        orderService = mock(OrderService.class);
        ProductService productService = mock(ProductService.class);
        OrderController controller = new OrderController(orderService, productService);
        mockMvc = MockMvcBuilders.standaloneSetup(controller)
            .setControllerAdvice(new ApiExceptionHandler())
            .build();
    }

    @Test
    void getOrderEndpointReturnsTheRequestedOrder() throws Exception {
        when(orderService.get(42L)).thenReturn(order("pending"));

        mockMvc.perform(get("/api/orders/{id}", 42L))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.id").value(42))
            .andExpect(jsonPath("$.orderNumber").value("ORD-R2-0042"))
            .andExpect(jsonPath("$.status").value("pending"))
            .andExpect(jsonPath("$.lines[0].sku").value("SKU-AUD-1001"))
            .andExpect(jsonPath("$.totalQuantity").value(2))
            .andExpect(jsonPath("$.orderTotal").value(199.90));

        verify(orderService).get(42L);
    }

    @Test
    void patchOrderStatusEndpointUpdatesAndReturnsTheOrder() throws Exception {
        StatusRequest request = new StatusRequest("shipped");
        when(orderService.updateStatus(42L, request)).thenReturn(order("shipped"));

        mockMvc.perform(patch("/api/orders/{id}/status", 42L)
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"status\":\"shipped\"}"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.id").value(42))
            .andExpect(jsonPath("$.orderNumber").value("ORD-R2-0042"))
            .andExpect(jsonPath("$.status").value("shipped"));

        verify(orderService).updateStatus(42L, request);
    }

    @Test
    void patchOrderStatusEndpointRejectsAnUnsupportedStatus() throws Exception {
        mockMvc.perform(patch("/api/orders/{id}/status", 42L)
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"status\":\"cancelled\"}"))
            .andExpect(status().isBadRequest())
            .andExpect(jsonPath("$.status").value(400))
            .andExpect(jsonPath("$.error").value("Validation failed"))
            .andExpect(jsonPath("$.fields.status").exists());

        verify(orderService, never()).updateStatus(42L, new StatusRequest("cancelled"));
    }

    private OrderResponse order(String status) {
        LocalDateTime orderedAt = LocalDateTime.of(2026, 10, 22, 10, 30);
        return new OrderResponse(
            42L,
            "ORD-R2-0042",
            "customer@example.com",
            status,
            orderedAt,
            orderedAt.plusMinutes(5),
            List.of(new OrderLineResponse(
                7L,
                "SKU-AUD-1001",
                "Aurora Wireless Headphones",
                2,
                new BigDecimal("99.95"),
                new BigDecimal("199.90")
            )),
            2,
            new BigDecimal("199.90")
        );
    }
}
