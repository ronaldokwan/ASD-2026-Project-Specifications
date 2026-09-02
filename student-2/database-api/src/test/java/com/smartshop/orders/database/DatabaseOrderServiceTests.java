package com.smartshop.orders.database;

import com.smartshop.orders.database.dto.OrderPayloads.OrderLineWriteRequest;
import com.smartshop.orders.database.dto.OrderPayloads.OrderResponse;
import com.smartshop.orders.database.dto.OrderPayloads.OrderWriteRequest;
import com.smartshop.orders.database.repository.OrderLineRepository;
import com.smartshop.orders.database.service.DatabaseOrderService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.web.server.ResponseStatusException;

import java.math.BigDecimal;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@SpringBootTest(properties = "spring.datasource.url=jdbc:sqlite::memory:")
class DatabaseOrderServiceTests {

    @Autowired
    private DatabaseOrderService orderService;

    @Autowired
    private OrderLineRepository lineRepository;

    @Test
    void createsAndCascadeDeletesOrderWithTwoLines() {
        long linesBefore = lineRepository.count();
        OrderResponse created = orderService.create(new OrderWriteRequest(
            "ORD-TEST-CASCADE",
            "test@example.com",
            "pending",
            List.of(
                new OrderLineWriteRequest(null, "TEST-A", 2, new BigDecimal("10.00")),
                new OrderLineWriteRequest(null, "TEST-B", 1, new BigDecimal("5.50"))
            )
        ));

        assertThat(created.lines()).hasSize(2);
        assertThat(created.orderTotal()).isEqualByComparingTo("25.50");
        assertThat(lineRepository.count()).isEqualTo(linesBefore + 2);

        orderService.delete(created.id());
        assertThat(lineRepository.count()).isEqualTo(linesBefore);
    }

    @Test
    void rejectsDuplicateSkuWithinOneOrder() {
        OrderWriteRequest request = new OrderWriteRequest(
            "ORD-TEST-DUPLICATE",
            "test@example.com",
            "pending",
            List.of(
                new OrderLineWriteRequest(null, "same-sku", 1, BigDecimal.ONE),
                new OrderLineWriteRequest(null, "SAME-SKU", 2, BigDecimal.TEN)
            )
        );

        assertThatThrownBy(() -> orderService.create(request))
            .isInstanceOf(ResponseStatusException.class)
            .hasMessageContaining("Duplicate SKU");
    }
}
