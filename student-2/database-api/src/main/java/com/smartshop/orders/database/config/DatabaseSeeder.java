package com.smartshop.orders.database.config;

import com.smartshop.orders.database.dto.OrderPayloads.OrderLineWriteRequest;
import com.smartshop.orders.database.dto.OrderPayloads.OrderWriteRequest;
import com.smartshop.orders.database.repository.OrderRepository;
import com.smartshop.orders.database.service.DatabaseOrderService;
import org.springframework.boot.CommandLineRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.math.BigDecimal;
import java.util.List;

@Configuration
public class DatabaseSeeder {

    @Bean
    CommandLineRunner seedOrders(OrderRepository repository, DatabaseOrderService orderService) {
        return args -> {
            if (repository.count() > 0) {
                return;
            }

            String[] statuses = {"pending", "shipped", "delivered"};
            for (int index = 1; index <= 10; index++) {
                String suffix = String.format("%03d", index);
                orderService.create(new OrderWriteRequest(
                    "ORD-SEED-" + suffix,
                    "customer" + index + "@example.com",
                    statuses[(index - 1) % statuses.length],
                    List.of(
                        new OrderLineWriteRequest(null, "SKU-" + suffix, index % 3 + 1,
                            BigDecimal.valueOf(10L + index)),
                        new OrderLineWriteRequest(null, "BONUS-" + suffix, 1,
                            BigDecimal.valueOf(4.50 + index))
                    )
                ));
            }
        };
    }
}
