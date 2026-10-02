# SmartShop Order Shipping Policy

This is the internal shipping policy for the SmartShop teaching project.

1. An order may proceed to shipment only when its status is `pending`, it contains at least one valid order line, its total quantity and order total are positive, and inventory was committed when the order was saved.
2. An order that is already `shipped` or `delivered` is not awaiting shipment and must not be shipped a second time.
3. An order with missing or unconfirmed inventory must be reviewed and must not proceed to shipment.
4. A delayed pending order must be reviewed before a delivery date is communicated to the customer. The customer should receive a concise apology and an accurate status update.
5. A delivered order cannot be moved back to `pending`. Any return or refund requires a separate process that is outside the current Customer Orders feature.
6. When the available order facts or policy context do not answer a question, the system must report insufficient context rather than inventing an answer.
