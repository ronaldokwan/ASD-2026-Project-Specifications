package com.smartshop.orders.backend.service;

import com.smartshop.orders.backend.client.RagClient;
import com.smartshop.orders.backend.dto.OrderIntelligenceModels.RagAnswerResponse;
import com.smartshop.orders.backend.dto.OrderIntelligenceModels.RagDocument;
import com.smartshop.orders.backend.dto.OrderIntelligenceModels.RagWriteResponse;
import com.smartshop.orders.backend.dto.OrderModels.OrderResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.Resource;
import org.springframework.stereotype.Service;
import org.springframework.util.StreamUtils;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

@Service
public class OrderRagService {

    private static final Logger logger = LoggerFactory.getLogger(OrderRagService.class);
    private static final String POLICY_ID = "orders-shipping-policy-v1";
    private static final String MEANINGFUL_QUESTION_MESSAGE =
        "Please enter a meaningful question about the order or shipping policy.";
    private static final Pattern ALPHABETIC_WORD = Pattern.compile("\\p{L}+");

    private final RagClient ragClient;
    private final String shippingPolicy;

    public OrderRagService(
        RagClient ragClient,
        @Value("classpath:rag/shipping-policy.md") Resource policyResource
    ) throws IOException {
        this.ragClient = ragClient;
        this.shippingPolicy = StreamUtils.copyToString(
            policyResource.getInputStream(), StandardCharsets.UTF_8
        );
    }

    public RagWriteResponse syncOrder(OrderResponse order) {
        return ragClient.upsertDocuments(List.of(orderDocument(order), policyDocument()));
    }

    public void syncOrderBestEffort(OrderResponse order) {
        try {
            syncOrder(order);
        } catch (RuntimeException exception) {
            logger.warn("Order {} was saved but its RAG context could not be synchronised: {}",
                order.orderNumber(), exception.getMessage());
        }
    }

    public void removeOrderBestEffort(long orderId) {
        try {
            ragClient.deleteDocument(orderDocumentId(orderId));
        } catch (RuntimeException exception) {
            logger.warn("Order {} was deleted but its RAG document could not be removed: {}",
                orderId, exception.getMessage());
        }
    }

    public RagAnswerResponse ask(OrderResponse order, String question) {
        String normalisedQuestion = question == null ? "" : question.trim();
        if (!isMeaningfulQuestion(normalisedQuestion, order.orderNumber())) {
            return new RagAnswerResponse(
                "insufficient_context",
                null,
                MEANINGFUL_QUESTION_MESSAGE,
                "insufficient",
                List.of(),
                0,
                0,
                null
            );
        }

        String groundedQuestion = "For order " + order.orderNumber() + ": " + normalisedQuestion;
        return ragClient.ask(groundedQuestion, order.orderNumber());
    }

    private boolean isMeaningfulQuestion(String question, String orderNumber) {
        if (question.isBlank() || question.equalsIgnoreCase(orderNumber)) {
            return false;
        }

        Matcher words = ALPHABETIC_WORD.matcher(question);
        int wordCount = 0;
        while (words.find() && wordCount < 2) {
            wordCount++;
        }
        return wordCount >= 2;
    }

    private RagDocument orderDocument(OrderResponse order) {
        String skus = order.lines().stream()
            .map(line -> line.sku())
            .collect(Collectors.joining(", "));
        String text = """
            Order number: %s.
            Status: %s.
            Line count: %d.
            Total quantity: %d.
            Order total: $%s.
            Products: %s.
            Inventory was committed when the order was saved.
            """.formatted(
                order.orderNumber(), order.status(), order.lines().size(),
                order.totalQuantity(), order.orderTotal(), skus
            ).strip();
        return new RagDocument(
            orderDocumentId(order.id()),
            text,
            Map.of(
                "feature", "orders",
                "doc_type", "order",
                "source_authority", "primary",
                "order_number", order.orderNumber(),
                "order_id", order.id()
            )
        );
    }

    private RagDocument policyDocument() {
        return new RagDocument(
            POLICY_ID,
            shippingPolicy,
            Map.of(
                "feature", "orders",
                "doc_type", "shipping_policy",
                "source_authority", "policy"
            )
        );
    }

    private String orderDocumentId(long orderId) {
        return "order-" + orderId;
    }
}
