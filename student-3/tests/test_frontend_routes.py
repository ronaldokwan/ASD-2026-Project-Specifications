"""Frontend routes and HTMX fragment tests."""

import api_client


def form_data(**overrides):
    data = {"name": "New Customer", "email": "new@example.test", "phone": "",
            "address": "Sydney NSW", "loyalty_tier": "Bronze", "joined_at": "2026-09-03"}
    data.update(overrides)
    return data


def test_index_renders_customers_and_shared_design(frontend, fake_api):
    html = frontend.get("/").get_data(as_text=True)
    assert "Customer Account Management" in html
    assert "Avery Brooks" in html
    assert "/shared/css/theme.css" in html
    assert 'id="customer-form"' in html
    assert "Add a customer" in html
    assert "Actions" in html
    assert 'aria-label="Suggest reward for Avery Brooks"' in html
    assert ">#1<" not in html


def test_search_partial(frontend, fake_api, monkeypatch):
    html = frontend.get("/partials/customers?search=avery").get_data(as_text=True)
    assert "<html" not in html
    assert 'id="customer-table"' in html
    assert "Avery Brooks" in html

    monkeypatch.setattr(
        api_client,
        "list_customers",
        lambda search=None: (_ for _ in ()).throw(
            api_client.ApiError("database unavailable", 503)
        ),
    )
    failed = frontend.get("/partials/customers?search=avery")
    assert failed.status_code == 503
    assert 'id="customer-table"' in failed.get_data(as_text=True)


def test_customer_detail(frontend, fake_api):
    html = frontend.get("/customers/1").get_data(as_text=True)
    assert "avery@example.test" in html
    assert "Sydney NSW" in html
    assert "Customer ID" not in html
    assert "Check Profile with MCP" in html
    assert "Customer #1" not in html


def test_create_returns_oob_updates(frontend, fake_api):
    html = frontend.post("/customers", data=form_data()).get_data(as_text=True)
    assert fake_api["created"][0]["email"] == "new@example.test"
    assert 'class="alert ok"' in html
    assert 'hx-swap-oob="true"' in html


def test_edit_form_and_update(frontend, fake_api):
    form = frontend.get("/partials/form/1").get_data(as_text=True)
    assert "Edit customer" in form
    assert "Save changes" in form
    assert "Cancel editing" in form
    assert "Editing selected customer." in form
    assert "Editing customer #1" not in form
    assert 'hx-post="/customers/1"' in form
    updated = frontend.post("/customers/1", data=form_data(name="Updated Customer"))
    assert "Updated Customer" in updated.get_data(as_text=True)


def test_delete_action(frontend, fake_api):
    html = frontend.post("/customers/1/delete").get_data(as_text=True)
    assert fake_api["deleted"] == [1]
    assert "Customer deleted." in html
    assert "Customer #1" not in html


def test_validation_error_is_safely_rendered(frontend, fake_api, monkeypatch):
    monkeypatch.setattr(api_client, "create_customer", lambda payload: (_ for _ in ()).throw(
        api_client.ApiError("validation failed", 400, ["email is required"])))
    html = frontend.post("/customers", data=form_data(email="")).get_data(as_text=True)
    assert "email is required" in html
    assert 'class="alert error"' in html


def test_ai_reward_result_and_trace(frontend, fake_api):
    html = frontend.post("/customers/1/ai-reward").get_data(as_text=True)
    assert "10% off the next purchase" in html
    assert "Plan" in html
    assert '<details class="trace-details">' in html
    assert "Technical agent trace" in html
    assert "not stored or automatically applied" in html


def test_frontend_health(frontend, monkeypatch):
    monkeypatch.setattr(api_client, "backend_health", lambda: {"status": "ok"})
    assert frontend.get("/health").get_json()["status"] == "ok"


def test_mcp_profile_result_is_structured_and_safe(frontend, fake_api, monkeypatch):
    html = frontend.post("/customers/1/mcp-profile").get_data(as_text=True)
    assert "Profile check complete" in html
    assert "629 days" in html
    assert "This result is not stored" in html

    monkeypatch.setattr(api_client, "check_customer_profile", lambda _customer_id: {
        "tool": "check_customer_profile", "tier_valid": False,
        "membership_days": None, "profile_status": "invalid",
        "missing_optional_fields": [], "warnings": [],
        "errors": ["<script>alert('x')</script>"],
    })
    unsafe = frontend.post("/customers/1/mcp-profile").get_data(as_text=True)
    assert "<script>" not in unsafe
    assert "&lt;script&gt;" in unsafe


def test_mcp_service_unavailable_is_displayed(frontend, fake_api, monkeypatch):
    monkeypatch.setattr(
        api_client, "check_customer_profile",
        lambda _customer_id: (_ for _ in ()).throw(
            api_client.ApiError("MCP server unavailable", 503)
        ),
    )
    response = frontend.post("/customers/1/mcp-profile")
    assert response.status_code == 503
    assert "MCP server unavailable" in response.get_data(as_text=True)


def test_multi_agent_frontend_shows_stages_evidence_and_human_controls(frontend, fake_api):
    response = frontend.post("/customers/1/multi-agent")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Model-generated plan" in html
    assert "Application-enforced requirements" in html
    assert "Check policy" in html
    assert "Cite policy" in html
    assert "Do not apply reward" in html
    assert "Worker recommendation" in html
    assert "Reviewer findings" in html
    assert "Supporting evidence" in html
    assert "Partially accept / correct" in html
    assert "Reject recommendation" in html
    assert "Does not" not in html


def test_multi_agent_human_decision_is_sent_to_backend(frontend, fake_api):
    response = frontend.post("/customers/1/multi-agent/workflow-123/review", data={
        "decision": "partial_accept",
        "feedback": "Corrected for the available evidence.",
        "corrected_recommendation": "Retain the benefit suggestion.",
        "corrected_rationale": "Policy source supports consideration.",
        "accepted_fields": "recommendation",
        "unresolved_issues": "Confirm eligibility before applying.",
    })
    assert response.status_code == 200
    assert "Partially Accepted" in response.get_data(as_text=True)
    assert fake_api["multi_agent_reviews"][0]["accepted_fields"] == ["recommendation"]
    assert fake_api["multi_agent_reviews"][0]["unresolved_issues"] == [
        "Confirm eligibility before applying.",
    ]


def test_partial_accept_validation_error_preserves_entered_values(
    frontend, fake_api, monkeypatch
):
    values = {
        "decision": "partial_accept",
        "feedback": "",
        "corrected_recommendation": "Bronze members may receive an approved policy benefit.",
        "corrected_rationale": "This is informational and does not apply a reward.",
        "accepted_fields": "Bronze tier\nApproved Bronze benefits",
        "unresolved_issues": "None for this wording correction",
    }

    def reject_review(*_args, **_kwargs):
        raise api_client.ApiError("Feedback is required for partial acceptance.", 400)

    monkeypatch.setattr(api_client, "review_multi_agent_workflow", reject_review)
    response = frontend.post(
        "/customers/1/multi-agent/workflow-123/review", data=values
    )
    html = response.get_data(as_text=True)
    assert response.status_code == 400
    assert "Feedback is required for partial acceptance." in html
    for value in (
        "Bronze members may receive an approved policy benefit.",
        "This is informational and does not apply a reward.",
        "Bronze tier", "Approved Bronze benefits", "None for this wording correction",
    ):
        assert value in html
    assert 'name="feedback" required' in html


def test_review_error_after_save_displays_recorded_decision(frontend, fake_api, monkeypatch):
    saved_decision = {
        "decision": "partial_accept",
        "feedback": "Wording correction only; rewards remain informational.",
        "corrected_output": {
            "recommendation": "Bronze members may receive the listed policy benefits.",
            "rationale": "This does not establish eligibility or apply a reward.",
        },
        "accepted_fields": ["Bronze tier", "Approved Bronze benefits"],
        "unresolved_issues": ["None for this wording correction"],
    }
    monkeypatch.setattr(api_client, "review_multi_agent_workflow", lambda *_args, **_kwargs: (
        _ for _ in ()
    ).throw(api_client.ApiError("The response could not be confirmed.", 502)))
    monkeypatch.setattr(api_client, "get_multi_agent_workflow", lambda *_args: {
        "workflow_id": "workflow-123", "status": "partially_accepted",
        "human_decision": saved_decision,
    })

    response = frontend.post(
        "/customers/1/multi-agent/workflow-123/review",
        data={"decision": "partial_accept", "feedback": "retry"},
    )
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "A decision was already recorded" in html
    assert "Bronze members may receive the listed policy benefits." in html
    assert "None for this wording correction" in html
    assert "Administrator decision" not in html


def test_multi_agent_history_fragment(frontend, fake_api):
    response = frontend.get("/customers/1/multi-agent/history")
    assert response.status_code == 200
    assert "Workflow history" in response.get_data(as_text=True)
    assert "workflow-123" in response.get_data(as_text=True)


def test_multi_agent_history_is_newest_first_and_shows_five_more_at_a_time(
    frontend, fake_api, monkeypatch
):
    workflows = [
        {
            "workflow_id": "workflow-{}".format(number),
            "status": "failed" if number == 12 else "human_review",
            "created_at": "2026-10-{:02d}T00:00:00+00:00".format(number),
            "human_decision": {"decision": "accept"} if number == 12 else None,
        }
        for number in range(1, 13)
    ]
    monkeypatch.setattr(api_client, "list_multi_agent_workflows", lambda _customer_id: {
        "count": len(workflows), "workflows": workflows,
    })

    first_page = frontend.get("/customers/1/multi-agent/history")
    html = first_page.get_data(as_text=True)
    assert first_page.status_code == 200
    positions = [html.index("workflow-{}\"".format(number)) for number in (12, 11, 10, 9, 8)]
    assert positions == sorted(positions)
    assert "workflow-8\"" in html
    assert "workflow-7\"" not in html
    assert "Failed" in html
    assert "Accept" in html
    assert "2026-10-12T00:00:00+00:00" in html
    assert 'hx-get="/customers/1/multi-agent/history?offset=5"' in html

    second_page = frontend.get("/customers/1/multi-agent/history?offset=5")
    html = second_page.get_data(as_text=True)
    assert 'id="multi-agent-history-list"' in html
    assert "workflow-8\"" in html
    assert "workflow-3\"" in html
    assert "workflow-2\"" not in html
    assert 'hx-get="/customers/1/multi-agent/history?offset=10"' in html

    final_page = frontend.get("/customers/1/multi-agent/history?offset=10")
    html = final_page.get_data(as_text=True)
    assert "workflow-2\"" in html and "workflow-1\"" in html
    assert "Show more" not in html
    assert 'hx-get="/customers/1/multi-agent/workflow-1"' in html

    older_workflow = {
        "workflow_id": "workflow-1", "status": "human_review",
        "stage": "human_review", "created_at": "2026-10-01T00:00:00+00:00",
        "plan": {}, "worker_result": {}, "reviewer_result": {}, "evidence": [],
        "roles": [], "completion_gate": {},
    }
    monkeypatch.setattr(
        api_client, "get_multi_agent_workflow",
        lambda _customer_id, workflow_id: dict(older_workflow, workflow_id=workflow_id),
    )
    viewed = frontend.get("/customers/1/multi-agent/workflow-1")
    assert viewed.status_code == 200
    assert "workflow-1" in viewed.get_data(as_text=True)


def test_multi_agent_history_hides_show_more_when_five_or_fewer(
    frontend, fake_api, monkeypatch
):
    workflows = [
        {"workflow_id": "workflow-{}".format(number), "status": "failed",
         "created_at": "2026-10-{:02d}T00:00:00+00:00".format(number)}
        for number in range(1, 6)
    ]
    monkeypatch.setattr(api_client, "list_multi_agent_workflows", lambda _customer_id: {
        "count": len(workflows), "workflows": workflows,
    })
    response = frontend.get("/customers/1/multi-agent/history")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert all("workflow-{}\"".format(number) in html for number in range(1, 6))
    assert "Show more" not in html


def test_rag_answer_displays_sources_and_confidence(frontend, fake_api):
    html = frontend.post(
        "/loyalty-benefits/ask",
        data={"question": "What benefits are available to Gold customers?"},
    ).get_data(as_text=True)
    assert "fifteen percent off" in html
    assert "customer-loyalty-policy.md" in html
    assert "Gold Membership" in html
    assert "Confidence:" in html and "High" in html
    assert "not stored in the customer database" in html


def test_rag_insufficient_context_is_displayed(frontend, fake_api, monkeypatch):
    monkeypatch.setattr(api_client, "ask_loyalty_benefits", lambda _question: {
        "status": "insufficient_context", "answer": "", "sources": [],
        "confidence": "insufficient", "message": "Insufficient relevant context was found.",
    })
    html = frontend.post(
        "/loyalty-benefits/ask", data={"question": "How do I reset a password?"}
    ).get_data(as_text=True)
    assert "Insufficient context" in html
    assert "Insufficient relevant context was found" in html


def test_rag_service_unavailable_and_unsafe_html_are_safe(
    frontend, fake_api, monkeypatch
):
    monkeypatch.setattr(
        api_client, "ask_loyalty_benefits",
        lambda _question: (_ for _ in ()).throw(
            api_client.ApiError("RAG service unavailable", 503)
        ),
    )
    unavailable = frontend.post(
        "/loyalty-benefits/ask", data={"question": "Gold benefits?"}
    )
    assert unavailable.status_code == 503
    assert "RAG service unavailable" in unavailable.get_data(as_text=True)

    monkeypatch.setattr(api_client, "ask_loyalty_benefits", lambda _question: {
        "status": "ok", "answer": "<script>alert('answer')</script>",
        "confidence": "low", "sources": [{
            "source": "<img src=x onerror=alert(1)>",
            "section": "Gold <b>Membership</b>",
            "snippet": "<script>alert('source')</script>",
        }],
    })
    html = frontend.post(
        "/loyalty-benefits/ask", data={"question": "Gold benefits?"}
    ).get_data(as_text=True)
    assert "<script>" not in html
    assert "<img" not in html
    assert "&lt;script&gt;" in html
