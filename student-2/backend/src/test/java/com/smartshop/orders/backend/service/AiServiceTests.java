package com.smartshop.orders.backend.service;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.client.ExpectedCount.once;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.content;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

class AiServiceTests {

    private MockRestServiceServer server;
    private AiService service;

    @BeforeEach
    void setUp() {
        RestClient.Builder builder = RestClient.builder().baseUrl("http://localhost:7001");
        server = MockRestServiceServer.bindTo(builder).build();
        service = new AiService(builder.build());
    }

    @Test
    void sendsGenerationThroughTheSharedAgenticLoop() {
        server.expect(once(), requestTo("http://localhost:7001/agent/run"))
            .andExpect(content().json("""
                {
                  "goal":"shipping_delay_email",
                  "task":"Draft an email",
                  "context":{"order_number":"ORD-100"},
                  "fallback":{"content":"Fallback email"}
                }
                """))
            .andRespond(withSuccess("""
                {
                  "ok":true,
                  "result":{"content":"Generated email for ORD-100"},
                  "fallback_used":false,
                  "trace":[{"step":"Plan"},{"step":"Act"},{"step":"Observe"}]
                }
                """, MediaType.APPLICATION_JSON));

        var response = service.generate(
            "shipping_delay_email",
            "Draft an email",
            Map.of("order_number", "ORD-100"),
            "Fallback email"
        );

        assertThat(response.content()).isEqualTo("Generated email for ORD-100");
        assertThat(response.generatedByAiMode()).isTrue();
        server.verify();
    }

    @Test
    void identifiesTheDeterministicAiModeFallback() {
        server.expect(once(), requestTo("http://localhost:7001/agent/run"))
            .andRespond(withSuccess("""
                {
                  "ok":true,
                  "result":{"content":"Fallback email"},
                  "fallback_used":true
                }
                """, MediaType.APPLICATION_JSON));

        var response = service.generate(
            "shipping_delay_email",
            "Draft an email",
            Map.of("order_number", "ORD-100"),
            "Fallback email"
        );

        assertThat(response.content()).isEqualTo("Fallback email");
        assertThat(response.generatedByAiMode()).isFalse();
        server.verify();
    }
}
