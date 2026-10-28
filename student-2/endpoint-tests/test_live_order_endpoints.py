#!/usr/bin/env python3
"""Post-commit checks against the running Student 2 backend container."""

from __future__ import annotations

import json
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BACKEND_URL = "http://localhost:8002"
DATABASE_URL = "http://localhost:9002"


def request_json(method: str, url: str, payload: dict | None = None) -> tuple[int, dict]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else {}
    except HTTPError as error:
        body = error.read().decode("utf-8")
        return error.code, json.loads(body) if body else {}


def wait_for_backend() -> None:
    for _ in range(30):
        try:
            status, _ = request_json("GET", f"{BACKEND_URL}/actuator/health")
            if status == 200:
                return
        except (URLError, TimeoutError, json.JSONDecodeError):
            pass
        time.sleep(2)
    raise AssertionError("Student 2 backend did not become healthy")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    wait_for_backend()
    order_id: int | None = None
    unique = time.time_ns()
    fixture = {
        "orderNumber": f"ORD-CI-{unique}",
        "customerEmail": f"ci-{unique}@example.com",
        "status": "pending",
        "lines": [
            {
                "sku": "SKU-CI-0001",
                "quantity": 2,
                "unitPrice": 19.95,
            }
        ],
    }

    try:
        create_status, created = request_json(
            "POST", f"{DATABASE_URL}/internal/orders", fixture
        )
        require(create_status == 201, f"fixture creation returned HTTP {create_status}")
        order_id = int(created["id"])

        get_status, fetched = request_json(
            "GET", f"{BACKEND_URL}/api/orders/{order_id}"
        )
        require(get_status == 200, f"GET order returned HTTP {get_status}")
        require(fetched.get("id") == order_id, "GET returned a different order id")
        require(
            fetched.get("orderNumber") == fixture["orderNumber"],
            "GET returned a different order number",
        )
        require(fetched.get("status") == "pending", "GET returned the wrong status")
        require(fetched.get("totalQuantity") == 2, "GET returned the wrong quantity")
        print(
            "PASSED live GET /api/orders/{id}: persisted order returned through "
            "backend -> database API"
        )

        patch_status, updated = request_json(
            "PATCH",
            f"{BACKEND_URL}/api/orders/{order_id}/status",
            {"status": "shipped"},
        )
        require(patch_status == 200, f"valid PATCH returned HTTP {patch_status}")
        require(updated.get("status") == "shipped", "PATCH did not return shipped")
        print(
            "PASSED live PATCH /api/orders/{id}/status: valid status was persisted"
        )

        invalid_status, invalid_body = request_json(
            "PATCH",
            f"{BACKEND_URL}/api/orders/{order_id}/status",
            {"status": "cancelled"},
        )
        require(invalid_status == 400, f"invalid PATCH returned HTTP {invalid_status}")
        require(
            invalid_body.get("error") == "Validation failed",
            "invalid PATCH did not return the validation error",
        )

        final_status, final_order = request_json(
            "GET", f"{BACKEND_URL}/api/orders/{order_id}"
        )
        require(final_status == 200, f"final GET returned HTTP {final_status}")
        require(
            final_order.get("status") == "shipped",
            "invalid PATCH changed the persisted order",
        )
        print(
            "PASSED live PATCH validation: unsupported status returned HTTP 400 "
            "without changing the order"
        )
        print("3/3 live endpoint checks passed against the Student 2 containers")
        return 0
    except (AssertionError, KeyError, TypeError, ValueError, URLError) as error:
        print(f"FAILED live endpoint checks: {error}", file=sys.stderr)
        return 1
    finally:
        if order_id is not None:
            try:
                request_json("DELETE", f"{DATABASE_URL}/internal/orders/{order_id}")
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
                print(
                    f"WARNING: could not remove test fixture order {order_id}",
                    file=sys.stderr,
                )


if __name__ == "__main__":
    raise SystemExit(main())
