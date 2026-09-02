package com.smartshop.orders.backend.service;

import com.smartshop.orders.backend.dto.OrderModels.StockCheckResult;
import com.smartshop.orders.backend.dto.OrderModels.StockItemRequest;
import com.smartshop.orders.backend.dto.OrderModels.StockUpdateResult;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class StockService {
    //todo
    public StockCheckResult checkStock(List<StockItemRequest> items) {
        return new StockCheckResult(true, "Stock is sufficient (fixed development response)");
    }
    //todo
    public StockUpdateResult deductStock(String orderNumber, List<StockItemRequest> items) {
        return new StockUpdateResult(true, "Stock updated successfully (fixed development response)");
    }
}
