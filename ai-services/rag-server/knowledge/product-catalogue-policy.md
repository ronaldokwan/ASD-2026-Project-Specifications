<!-- rag-feature: product_catalogue -->
# Product Catalogue Policy

Owner: Student 1 - Product Catalogue. Each section is kept under 200
characters so a whole section fits in one RAG citation snippet, and each
section uses the words a shopper or administrator would ask with, because
retrieval matches on shared keywords.

## Categories
The catalogue accepts only four categories: Audio, Computing, Home and Wearables. Any other category is rejected.

## Pricing Rules
The allowed price range is 1 to 9999 AUD. Every price is in Australian dollars and is stored to two decimal places.

## Listing Status
Active listings are visible to shoppers. Draft listings are still being prepared and are not visible. Archived listings are hidden but kept for history.

## SKU Format
Each new item gets a unique SKU such as SKU-AUD-1004: SKU, the first three letters of its category, then the next free number.

## Listing Readiness
A listing is ready to publish when it is active, has a valid category and price, and has a description of at least eight words.

## AI Suggestions
AI-generated descriptions and suggested prices are drafts. Nothing is saved until the administrator applies the suggestion and presses Create product.

## Deleting Items
Deleting an item removes it permanently. To hide an item but keep its history, archive it instead of deleting it.
