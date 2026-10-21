from langgraph.types import Command

from propertyscout.bootstrap import initial_state
from propertyscout.persistence import open_sqlite_graph
from propertyscout.schemas import WorkflowStage


def test_sqlite_checkpoint_resumes_after_graph_is_reopened(tmp_path) -> None:
    database_path = tmp_path / "propertyscout.sqlite"
    config = {"configurable": {"thread_id": "durable-shortlist"}}

    with open_sqlite_graph(database_path) as first_graph:
        paused = first_graph.invoke(initial_state("shortlist"), config)
        assert "__interrupt__" in paused
        assert paused["current_stage"] == WorkflowStage.ANALYSIS

    assert database_path.exists()
    assert database_path.stat().st_size > 0

    # A new connection and graph instance simulate restarting the application.
    with open_sqlite_graph(database_path) as restarted_graph:
        resumed = restarted_graph.invoke(
            Command(resume={"decision": "approved", "decided_by": "restart-test"}),
            config,
        )

    assert "__interrupt__" in resumed
    assert resumed["current_stage"] == WorkflowStage.CONTACT_RESEARCH
    assert resumed["approvals"]["shortlist"].decided_by == "restart-test"
    assert sum(event.action == "deal_initialized" for event in resumed["audit_events"]) == 1
