"""Agent turn 软超时调度（无 DB、无网络）。"""

from __future__ import annotations

from app.core.agent_turn import (
    WRITE_HARD_CANCEL_S,
    WRITE_SOFT_TIMEOUT_S,
    hard_timeout_error,
    plan_next_wait,
    soft_timeout_event,
    turn_meta_event,
)


def test_plan_before_soft_uses_keepalive_slice():
    plan = plan_next_wait(elapsed_s=10.0, keepalive_s=15.0)
    assert plan.emit_soft_timeout is False
    assert plan.hard_cancel is False
    assert plan.wait_s == 15.0


def test_plan_near_soft_boundary_shortens_wait():
    plan = plan_next_wait(elapsed_s=175.0, soft_timeout_s=180.0, keepalive_s=15.0)
    assert plan.emit_soft_timeout is False
    assert plan.hard_cancel is False
    assert plan.wait_s == 5.0


def test_plan_emits_soft_once_at_boundary():
    plan = plan_next_wait(elapsed_s=180.0, soft_timeout_s=180.0)
    assert plan.emit_soft_timeout is True
    assert plan.hard_cancel is False


def test_plan_skips_soft_when_already_emitted():
    plan = plan_next_wait(
        elapsed_s=185.0, soft_timeout_s=180.0, soft_already_emitted=True
    )
    assert plan.emit_soft_timeout is False
    assert plan.hard_cancel is False


def test_plan_hard_cancel_wins_over_soft():
    plan = plan_next_wait(
        elapsed_s=210.0, soft_timeout_s=180.0, hard_cancel_s=210.0
    )
    assert plan.hard_cancel is True
    assert plan.emit_soft_timeout is False


def test_adr_constants_match_spec():
    assert WRITE_SOFT_TIMEOUT_S == 180.0
    assert WRITE_HARD_CANCEL_S == 210.0


def test_event_shapes():
    meta = turn_meta_event(write_op="continue")
    assert meta["type"] == "meta"
    assert meta["passthrough"] is True
    assert meta["softTimeoutS"] == WRITE_SOFT_TIMEOUT_S

    soft = soft_timeout_event(elapsed_s=180.0, hard_cancel_s=WRITE_HARD_CANCEL_S)
    assert soft["type"] == "soft_timeout"
    assert "继续等待" in soft["message"]

    hard = hard_timeout_error(elapsed_s=210.0, hard_cancel_s=WRITE_HARD_CANCEL_S)
    assert hard["type"] == "error"
    assert hard["code"] == "hard_timeout"
