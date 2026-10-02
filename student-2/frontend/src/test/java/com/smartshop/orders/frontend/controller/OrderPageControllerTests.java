package com.smartshop.orders.frontend.controller;

import com.smartshop.orders.frontend.dto.FrontendModels.RagSource;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class OrderPageControllerTests {

    @Test
    void groupsSourceChunksByDocumentAndCreatesFriendlyLabels() {
        var sources = OrderPageController.groupSources(List.of(
            new RagSource(
                "orders-shipping-policy-v1",
                "SmartShop policy rule one."
            ),
            new RagSource(
                "order-67",
                "Order number: ORD-20260903-173210-E2EE0B. Status: pending."
            ),
            new RagSource(
                "orders-shipping-policy-v1",
                "SmartShop policy rule four."
            )
        ));

        assertThat(sources).hasSize(2);
        assertThat(sources.get(0).label()).isEqualTo("SmartShop Shipping Policy");
        assertThat(sources.get(0).snippets()).containsExactly(
            "SmartShop policy rule one.",
            "SmartShop policy rule four."
        );
        assertThat(sources.get(1).label()).isEqualTo("Order ORD-20260903-173210-E2EE0B");
    }
}
