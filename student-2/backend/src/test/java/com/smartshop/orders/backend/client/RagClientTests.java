package com.smartshop.orders.backend.client;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.client.ExpectedCount.once;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.content;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

class RagClientTests {

    private MockRestServiceServer server;
    private RagClient client;

    @BeforeEach
    void setUp() {
        RestClient.Builder builder = RestClient.builder().baseUrl("http://localhost:7003");
        server = MockRestServiceServer.bindTo(builder).build();
        client = new RagClient(builder.build(), true);
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
}
