package com.smartshop.orders.backend.service;

import com.smartshop.orders.backend.dto.OrderModels.ProductInfo;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;

@Service
public class ProductService {

    public ProductInfo getProductBySku(String sku) {
        //todo
        String normalisedSku = sku == null ? "UNKNOWN" : sku.trim().toUpperCase();
        return new ProductInfo(
            normalisedSku,
            "Mock product " + normalisedSku,
            new BigDecimal("19.99")
        );
    }
}
