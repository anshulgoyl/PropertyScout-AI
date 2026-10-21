from uuid import uuid4

import pytest

from propertyscout.email_gateway import FakeEmailGateway
from propertyscout.nodes import create_send_outreach
from propertyscout.outreach import TemplateOutreachDraftingService
from propertyscout.schemas import ApprovalDecision, ApprovalRecord
from tests.test_outreach import outreach_state


def approved_outreach_state():
    state = outreach_state()
    state["run_id"] = uuid4()
    state["outreach_draft"] = TemplateOutreachDraftingService().draft(
        state["property"],
        state["selected_contact"],
        state["analysis"],
    )
    state["approvals"] = {
        "outreach": ApprovalRecord(
            approval_type="outreach",
            decision=ApprovalDecision.APPROVED,
            decided_by="test-investor",
        )
    }
    return state


def test_replaying_send_node_does_not_duplicate_email() -> None:
    gateway = FakeEmailGateway()
    node = create_send_outreach(gateway)
    state = approved_outreach_state()

    first = node(state)
    second = node(state)

    assert gateway.send_attempts == 2
    assert len(gateway.sent_messages) == 1
    assert first["email_send_receipt"] == second["email_send_receipt"]
    assert first["idempotency_keys"] == second["idempotency_keys"]


def test_unapproved_outreach_cannot_be_sent() -> None:
    gateway = FakeEmailGateway()
    node = create_send_outreach(gateway)
    state = approved_outreach_state()
    state["approvals"]["outreach"].decision = ApprovalDecision.REJECTED

    with pytest.raises(ValueError, match="approved"):
        node(state)

    assert not gateway.sent_messages
