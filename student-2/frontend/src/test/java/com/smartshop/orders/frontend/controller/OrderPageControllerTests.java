package com.smartshop.orders.frontend.controller;

import com.smartshop.orders.frontend.dto.FrontendModels.RagSource;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class OrderPageControllerTests {

    @Test
    void orderPageExposesTheMultiAgentRolesAndReviewEntryPoint() throws IOException {
        String page = resource("/templates/order-detail.html");

        assertThat(page).contains(
            "Run Multi-Agent review",
            "Planner",
            "Worker",
            "Reviewer"
        );
    }

    @Test
    void workflowResultExposesAllHumanReviewModes() throws IOException {
        String fragment = resource("/templates/fragments/multi-agent-result.html");

        assertThat(fragment).contains(
            "Human Review · Final decision required",
            "Accept recommendation",
            "Partially accept with corrections",
            "Reject recommendation"
        );
    }

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

    private String resource(String path) throws IOException {
        try (InputStream input = getClass().getResourceAsStream(path)) {
            assertThat(input).as("classpath resource %s", path).isNotNull();
            return new String(input.readAllBytes(), StandardCharsets.UTF_8);
        }
    }
}
