package com.smartshop.orders.backend;

import com.smartshop.orders.backend.dto.OrderModels.ProductInfo;
import com.smartshop.orders.backend.service.ProductService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;
import org.springframework.web.server.ResponseStatusException;

import java.math.BigDecimal;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.ExpectedCount.once;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withStatus;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

class ProductServiceTests {

    private MockRestServiceServer server;
    private ProductService productService;

    @BeforeEach
    void setUp() {
        RestClient.Builder builder = RestClient.builder();
        server = MockRestServiceServer.bindTo(builder).build();
        productService = new ProductService(builder, "http://student-1-backend:8001");
    }

    @Test
    void returnsProductFromStudent1WrappedResponse() {
        server.expect(once(), requestTo("http://student-1-backend:8001/api/products?sku=SKU-AUD-1001"))
            .andExpect(method(HttpMethod.GET))
            .andRespond(withSuccess("""
                {
                  "count": 1,
                  "products": [
                    {
                      "id": 1,
                      "sku": "SKU-AUD-1001",
                      "name": "Aurora Wireless Headphones",
                      "price": 129.99,
                      "description": "Extra Student 1 field"
                    }
                  ]
                }
                """, MediaType.APPLICATION_JSON));

        ProductInfo result = productService.getProductBySku(" sku-aud-1001 ");

        assertThat(result.sku()).isEqualTo("SKU-AUD-1001");
        assertThat(result.name()).isEqualTo("Aurora Wireless Headphones");
        assertThat(result.price()).isEqualByComparingTo(new BigDecimal("129.99"));
        server.verify();
    }

    @Test
    void returnsFallbackWhenSkuIsNotFound() {
        server.expect(once(), requestTo("http://student-1-backend:8001/api/products?sku=NO-SUCH-SKU"))
            .andRespond(withSuccess("{\"count\":0,\"products\":[]}", MediaType.APPLICATION_JSON));

        ProductInfo result = productService.getProductBySku("no-such-sku");

        assertThat(result).isEqualTo(new ProductInfo("NO-SUCH-SKU", "NO-SUCH-SKU", BigDecimal.ZERO));
        server.verify();
    }

    @Test
    void returnsFallbackWhenStudent1IsUnavailable() {
        server.expect(once(), requestTo("http://student-1-backend:8001/api/products?sku=SKU-AUD-1001"))
            .andRespond(withStatus(HttpStatus.SERVICE_UNAVAILABLE));

        ProductInfo result = productService.getProductBySku("SKU-AUD-1001");

        assertThat(result).isEqualTo(new ProductInfo("SKU-AUD-1001", "SKU-AUD-1001", BigDecimal.ZERO));
        server.verify();
    }

    @Test
    void requiresARealProductForOrderCreation() {
        server.expect(once(), requestTo("http://student-1-backend:8001/api/products?sku=SKU-AUD-1001"))
            .andRespond(withSuccess("""
                {
                  "count": 1,
                  "products": [
                    {"sku":"SKU-AUD-1001","name":"Aurora Wireless Headphones","price":199.95}
                  ]
                }
                """, MediaType.APPLICATION_JSON));

        ProductInfo result = productService.requireProductBySku("SKU-AUD-1001");

        assertThat(result.price()).isEqualByComparingTo("199.95");
        server.verify();
    }

    @Test
    void rejectsAnUnknownProductForOrderCreation() {
        server.expect(once(), requestTo("http://student-1-backend:8001/api/products?sku=INVALID-SKU"))
            .andRespond(withSuccess("{\"count\":0,\"products\":[]}", MediaType.APPLICATION_JSON));

        assertThatThrownBy(() -> productService.requireProductBySku("INVALID-SKU"))
            .isInstanceOf(ResponseStatusException.class)
            .hasMessageContaining("400 BAD_REQUEST")
            .hasMessageContaining("Unknown product SKU: INVALID-SKU");
        server.verify();
    }

    @Test
    void rejectsOrderCreationWhenStudent1IsUnavailable() {
        server.expect(once(), requestTo("http://student-1-backend:8001/api/products?sku=SKU-AUD-1001"))
            .andRespond(withStatus(HttpStatus.SERVICE_UNAVAILABLE));

        assertThatThrownBy(() -> productService.requireProductBySku("SKU-AUD-1001"))
            .isInstanceOf(ResponseStatusException.class)
            .hasMessageContaining("503 SERVICE_UNAVAILABLE")
            .hasMessageContaining("Product catalogue is unavailable");
        server.verify();
    }

    @Test
    void listsProductsForTheOrderForm() {
        server.expect(once(), requestTo("http://student-1-backend:8001/api/products"))
            .andRespond(withSuccess("""
                {
                  "count": 2,
                  "products": [
                    {"sku":"SKU-AUD-1001","name":"Headphones","price":199.95},
                    {"sku":"SKU-COM-2001","name":"Keyboard","price":89.50}
                  ]
                }
                """, MediaType.APPLICATION_JSON));

        var products = productService.listProducts();

        assertThat(products).extracting(ProductInfo::sku)
            .containsExactly("SKU-AUD-1001", "SKU-COM-2001");
        server.verify();
    }
}
