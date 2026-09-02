package com.smartshop.orders.database.repository;

import com.smartshop.orders.database.entity.OrderEntity;
import org.springframework.data.jpa.repository.EntityGraph;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface OrderRepository extends JpaRepository<OrderEntity, Long> {

    @EntityGraph(attributePaths = "lines")
    List<OrderEntity> findAllByOrderByOrderedAtDesc();

    boolean existsByOrderNumber(String orderNumber);
}
