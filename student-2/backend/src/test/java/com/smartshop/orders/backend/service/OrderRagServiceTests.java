package com.smartshop.orders.backend.service;

import com.smartshop.orders.backend.client.RagClient;
import com.smartshop.orders.backend.dto.OrderIntelligenceModels.RagAnswerResponse;
import com.smartshop.orders.backend.dto.OrderModels.OrderResponse;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.core.io.ByteArrayResource;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.time.LocalDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class OrderRagServiceTests {

    private static final String ORDER_NUMBER = "ORD-20260902-163154-C7BC44";

    private RagClient ragClient;
    private OrderRagService ragService;
    private OrderResponse order;

    @BeforeEach
    void setUp() throws Exception {
        ragClient = mock(RagClient.class);
        ragService = new OrderRagService(
            ragClient,
            new ByteArrayResource("Shipping policy".getBytes(StandardCharsets.UTF_8))
        );
        order = new OrderResponse(
            41L,
            ORDER_NUMBER,
            "customer@example.com",
            "delivered",
            LocalDateTime.now(),
            LocalDateTime.now(),
            List.of(),
            0,
            BigDecimal.ZERO
        );
    }

    @Test
    void rejectsQuestionsWithoutMeaningfulIntentBeforeCallingRag() {
        for (String question : List.of("1", "abc", ORDER_NUMBER, "!!!")) {
            RagAnswerResponse response = ragService.ask(order, question);

            assertThat(response.status()).isEqualTo("insufficient_context");
            assertThat(response.confidence()).isEqualTo("insufficient");
            assertThat(response.sources()).isEmpty();
            assertThat(response.retrievedCount()).isZero();
            assertThat(response.message()).isEqualTo(
                "Please enter a meaningful question about the order or shipping policy."
            );
        }
        verifyNoInteractions(ragClient);
    }

    @Test
    void sendsMeaningfulQuestionThroughTheExistingGroundedFlow() {
        RagAnswerResponse expected = new RagAnswerResponse(
            "ok", "No.", null, "medium", List.of(), 2, 10, null
        );
        when(ragClient.ask(
            "For order " + ORDER_NUMBER + ": Can this order be shipped?",
            ORDER_NUMBER
        )).thenReturn(expected);

        RagAnswerResponse response = ragService.ask(order, " Can this order be shipped? ");

        assertThat(response).isSameAs(expected);
        verify(ragClient).ask(
            "For order " + ORDER_NUMBER + ": Can this order be shipped?",
            ORDER_NUMBER
        );
    }
}
