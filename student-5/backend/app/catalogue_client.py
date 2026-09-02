"""HTTP client for Student 1's Product Catalogue backend/API microservice.

Reviews only store a ``product_sku`` (see database/schema.sql); this module
looks up the matching product name and category so the UI does not have to
show bare SKUs. Every call is best-effort: the Product Catalogue is a
different student's service, so if it is slow, unreachable or not yet running,
callers fall back to the raw SKU rather than failing the request.
"""

import requests

from .config import Config


def list_products():
    """All catalogue products, or [] if the catalogue can't be reached."""
    url = "{}/api/products".format(Config.CATALOGUE_URL)
    try:
        response = requests.get(url, timeout=Config.CATALOGUE_TIMEOUT)
        response.raise_for_status()
        return response.json().get("products", [])
    except (requests.RequestException, ValueError):
        return []


def product_name(sku):
    """The product's name for one SKU, or the SKU itself if it can't be found."""
    url = "{}/api/products".format(Config.CATALOGUE_URL)
    try:
        response = requests.get(url, params={"sku": sku}, timeout=Config.CATALOGUE_TIMEOUT)
        response.raise_for_status()
        products = response.json().get("products", [])
        if products:
            return products[0].get("name", sku)
    except (requests.RequestException, ValueError):
        pass
    return sku
