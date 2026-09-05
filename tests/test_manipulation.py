import pytest

from PhyAgentOS.forge.manipulation import (
    CoordinationMode,
    ExpectedEffect,
    ManipulationDag,
    ManipulationDagNode,
    ManipulationIntent,
    ManipulationOperation,
    NodeSettlementStatus,
    PlanCondition,
    PlanConditionKind,
    PlanConditionOutcome,
    ReplanCoordinator,
    RetryLineage,
    RouteFailure,
    compile_manipulation_intent,
)


def _node(node_id: str, *, depends_on=(), operation="observe", condition=None):
    return ManipulationDagNode(
        node_id=node_id,
        operation=operation,
        depends_on=depends_on,
        condition=condition or PlanCondition(),
        retry_lineage=RetryLineage(root_node_id=node_id),
        entity_ref="entity://red-block" if operation == "manipulate" else None,
        goal="move red block" if operation == "manipulate" else "",
        success_criteria=("red block is placed",) if operation == "manipulate" else (),
        allowed_arms=("left", "right") if operation == "manipulate" else (),
        resource_locks=("arm:left", "arm:right") if operation == "manipulate" else (),
        required_evidence_roles=(
            "observation", "candidate_set", "calibration", "geometry", "route_readiness"
        ) if operation == "manipulate" else (),
        expected_effects=(ExpectedEffect.ENTITY_POSE_CHANGE,) if operation == "manipulate" else (),
    )


def _intent() -> ManipulationIntent:
    return ManipulationIntent(
        task_id="task-1",
        revision_id="revision-1",
        node_id="pick",
        node_digest="a" * 64,
        entity_ref="entity://red-block",
        goal="move red block",
        success_criteria=("red block is placed",),
        allowed_arms=("left", "right"),
        coordination_mode=CoordinationMode.ALTERNATIVE_ARM,
        observation_ref="observation://scene-1/head_camera",
        scene_revision="scene-1",
        frame_id="head_camera",
        calibration_ref="artifact://calibration/head",
        candidate_set_ref="candidate-set://scene-1/head_camera",
        constraints=("preserve_scene_revision", "enforce_speed_policy"),
    )


def test_dag_is_dependency_ordered_and_conditioned():
    observe = _node("observe")
    pick = _node(
        "pick",
        depends_on=("observe",),
        operation=ManipulationOperation.MANIPULATE,
        condition=PlanCondition(
            kind=PlanConditionKind.NODE_STATE_EQUALS,
            node_id="observe",
            expected_state=NodeSettlementStatus.SUCCEEDED,
        ),
    )
    dag = ManipulationDag(task_id="task-1", revision_id="revision-1", nodes=(pick, observe))
    assert dag.topological_order() == ("observe", "pick")
    assert dag.ready_nodes({"observe"}, node_states={"observe": "succeeded"}) == (pick,)
    assert dag.ready_nodes({"observe"}, node_states={"observe": "failed"}) == ()
    assert PlanCondition(kind=PlanConditionKind.NODE_STATE_EQUALS, node_id="missing", expected_state="succeeded").evaluate(node_states={}, evidence_revisions={}) is PlanConditionOutcome.UNKNOWN
    assert PlanCondition(kind=PlanConditionKind.NODE_STATE_EQUALS, node_id="observe", expected_state="succeeded").evaluate(node_states={"observe": "corrupt"}, evidence_revisions={}) is PlanConditionOutcome.UNKNOWN


def test_dag_rejects_cycle_and_unknown_dependency():
    with pytest.raises(ValueError, match="cycle"):
        ManipulationDag(
            task_id="task-1",
            revision_id="revision-1",
            nodes=(_node("a", depends_on=("b",)), _node("b", depends_on=("a",))),
        )
    with pytest.raises(ValueError, match="unknown node"):
        ManipulationDag(task_id="task-1", revision_id="revision-1", nodes=(_node("a", depends_on=("missing",)),))


def test_dag_rejects_invalid_retry_lineage():
    with pytest.raises(ValueError, match="root"):
        ManipulationDag(
            task_id="task-1",
            revision_id="revision-1",
            nodes=(
                ManipulationDagNode(
                    node_id="retry",
                    operation=ManipulationOperation.OBSERVE,
                    retry_lineage=RetryLineage(root_node_id="root"),
                ),
            ),
        )
    root = _node("root")
    retry = ManipulationDagNode(
        node_id="retry",
        operation=ManipulationOperation.OBSERVE,
        depends_on=("root",),
        retry_lineage=RetryLineage(root_node_id="root", retry_index=1, parent_node_id="root"),
    )
    assert ManipulationDag(
        task_id="task-1", revision_id="revision-1", nodes=(retry, root)
    ).topological_order() == ("root", "retry")


def test_replan_signal_preserves_constraints_and_is_no_motion():
    failure = RouteFailure(
        candidate_ref="candidate://red/1",
        arm_ids=("left",),
        phase="transport",
        code="collision",
        owner="collision",
        detail="attached object intersects table",
    )
    signal = ReplanCoordinator().build_signal(_intent(), (failure,))
    assert signal.status == "replan_required"
    assert signal.preserved_constraints == ("preserve_scene_revision", "enforce_speed_policy")
    assert signal.motion_authorized is False
    assert signal.candidate_digest == signal.candidate_digest.lower()


def test_intent_compilation_binds_node_digest_and_live_evidence():
    node = _node("pick", operation=ManipulationOperation.MANIPULATE)
    intent = compile_manipulation_intent(
        "task-1",
        "revision-1",
        node,
        observation_ref="observation://scene-1/head_camera",
        scene_revision="scene-1",
        frame_id="head_camera",
        calibration_ref="artifact://calibration/head",
        candidate_set_ref="candidate-set://scene-1/head_camera",
        constraints=("preserve_scene_revision",),
    )
    assert intent.node_digest == node.node_digest
    assert intent.motion_authorized is False


def test_node_and_replan_digests_reject_tampering():
    node = _node("pick", operation=ManipulationOperation.MANIPULATE)
    payload = node.model_dump(mode="python")
    payload["goal"] = "different goal"
    with pytest.raises(ValueError, match="node_digest"):
        ManipulationDagNode.model_validate(payload)

    failure = RouteFailure(candidate_ref="candidate://red/1", arm_ids=("left",), phase="lift", code="no_lift", owner="readiness", detail="target did not lift")
    signal = ReplanCoordinator().build_signal(_intent(), (failure,))
    changed = signal.model_dump(mode="python")
    changed["next_actions"] = ("ignore_policy",)
    with pytest.raises(ValueError, match="candidate_digest"):
        type(signal).model_validate(changed)


def test_replan_signal_rejects_failure_for_disallowed_arm():
    failure = RouteFailure(
        candidate_ref="candidate://red/1",
        arm_ids=("third-arm",),
        phase="transport",
        code="collision",
        owner="collision",
        detail="blocked",
    )
    with pytest.raises(ValueError, match="allowed"):
        ReplanCoordinator().build_signal(_intent(), (failure,))
