"""Protocol-level checks against the registered MCP server object."""

import asyncio
import os
import sys

import httpx2

SERVICE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SERVICE_ROOT)

from mcp import Client  # noqa: E402
from mcp.server.transport_security import TransportSecuritySettings  # noqa: E402
from server import mcp  # noqa: E402


def test_registered_tools_are_callable_through_real_mcp():
    async def exercise_protocol():
        async with Client(mcp) as client:
            listed = await client.list_tools()
            names = [tool.name for tool in listed.tools]
            assert "check_review_quality" in names
            assert "review_quality_check" in names
            assert "check_customer_profile" in names

            response = await client.call_tool("check_customer_profile", {
                "loyalty_tier": "Gold",
                "joined_at": "2024-08-19",
                "has_phone": True,
                "has_address": True,
                "as_of_date": "2026-10-01",
            })
            assert response.is_error is False
            assert response.structured_content["tool"] == "check_customer_profile"
            assert response.structured_content["membership_days"] == 773

            compatibility = await client.call_tool("review_quality_check", {
                "review_text": "Battery life is excellent and charges quickly.",
                "rating": 5,
            })
            assert compatibility.is_error is False
            assert compatibility.structured_content["flagged"] is False

    asyncio.run(exercise_protocol())


def test_student_five_compatibility_route_is_cohosted_with_mcp():
    async def call_compatibility_route():
        app = mcp.streamable_http_app(
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=False
            )
        )
        transport = httpx2.ASGITransport(app=app)
        async with mcp.session_manager.run():
            async with httpx2.AsyncClient(
                transport=transport, base_url="http://localhost"
            ) as client:
                response = await client.post("/tools/check_review_quality", json={
                    "review_text": "Battery life is excellent and charges quickly.",
                    "rating": 5,
                })
                assert response.status_code == 200
                assert response.json()["result"]["flagged"] is False

    asyncio.run(call_compatibility_route())
