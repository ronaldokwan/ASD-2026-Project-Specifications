package com.smartshop.orders.frontend.controller;

import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.ControllerAdvice;
import org.springframework.web.bind.annotation.ExceptionHandler;

@ControllerAdvice
public class FrontendExceptionHandler {

    @ExceptionHandler(RuntimeException.class)
    public String handle(RuntimeException exception, Model model) {
        model.addAttribute("message", exception.getMessage() == null
            ? "The service is temporarily unavailable" : exception.getMessage());
        return "error";
    }
}
