package com.smartshop.orders.backend.client;

import com.smartshop.orders.backend.dto.OrderIntelligenceModels.RagDocument;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.client.ExpectedCount.once;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.content;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.header;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

class RagClientTests {

    private static final String SERVICE_TOKEN = "test-rag-service-token";

    private MockRestServiceServer server;
    private RagClient client;

    @BeforeEach
    void setUp() {
        RestClient.Builder builder = RestClient.builder().baseUrl("http://localhost:7003");
        server = MockRestServiceServer.bindTo(builder).build();
        client = new RagClient(builder.build(), true, SERVICE_TOKEN);
    }

    @Test
    void limitsQuestionsToOrderDocuments() {
        server.expect(once(), requestTo("http://localhost:7003/rag/query"))
            .andExpect(content().json("""
                {"query":"For order ORD-100: Can it ship?","top_k":5,"filters":{
                  "$and":[{"feature":"orders"},{"$or":[
                    {"order_number":"ORD-100"},{"doc_type":"shipping_policy"}
                  ]}]}}
                """))
            .andRespond(withSuccess("""
                {"status":"ok","answer":"It can ship.","confidence":"high",
                 "sources":[{"doc_id":"order-1","snippet":"Status: pending"}]}
                """, MediaType.APPLICATION_JSON));

        var response = client.ask("For order ORD-100: Can it ship?", "ORD-100");

        assertThat(response.answer()).isEqualTo("It can ship.");
        assertThat(response.sources()).extracting(source -> source.docId()).containsExactly("order-1");
        server.verify();
    }

    @Test
    void sendsServiceCredentialForDocumentWrites() {
        server.expect(once(), requestTo("http://localhost:7003/rag/documents"))
            .andExpect(header("X-RAG-Service-Token", SERVICE_TOKEN))
            .andExpect(content().json("""
                {"documents":[{"id":"order-1","text":"Order ORD-100","metadata":{}}]}
                """))
            .andRespond(withSuccess("""
                {"ok":true,"documents_indexed":1,"chunks_indexed":1}
                """, MediaType.APPLICATION_JSON));

        var response = client.upsertDocuments(List.of(
            new RagDocument("order-1", "Order ORD-100", Map.of())
        ));

        assertThat(response.ok()).isTrue();
        server.verify();
    }

    @Test
    void sendsServiceCredentialForDocumentDeletes() {
        server.expect(once(), requestTo("http://localhost:7003/rag/documents/order-1"))
            .andExpect(header("X-RAG-Service-Token", SERVICE_TOKEN))
            .andRespond(withSuccess("""
                {"ok":true,"chunks_removed":1}
                """, MediaType.APPLICATION_JSON));

        var response = client.deleteDocument("order-1");

        assertThat(response.ok()).isTrue();
        server.verify();
    }
}
