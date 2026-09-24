from tools.indeed_resume_agent.api_client import QueueStats
from tools.indeed_resume_agent.ui_v2 import build_ui_state
from tools.indeed_resume_agent.ui_v3 import _layout_for_width, _status_tone
from tools.indeed_resume_agent.worker import WorkerSnapshot


def test_wide_layout_centers_compact_content_without_overstretching():
    layout = _layout_for_width(1366)

    assert layout.metric_columns == 3
    assert layout.sync_columns == 3
    assert layout.operation_columns == 3
    assert layout.max_content_width == 980
    assert layout.shell_padding == 18


def test_compact_layout_keeps_actions_dense_without_overstretching():
    layout = _layout_for_width(840)

    assert layout.metric_columns == 3
    assert layout.sync_columns == 3
    assert layout.operation_columns == 3
    assert layout.max_content_width == 820
    assert layout.shell_padding == 12


def test_narrow_layout_stacks_actions_and_metric_cards_for_small_screens():
    layout = _layout_for_width(720)

    assert layout.metric_columns == 2
    assert layout.sync_columns == 1
    assert layout.operation_columns == 2
    assert layout.max_content_width == 700
    assert layout.shell_padding == 10


def _ui_state(*, state: str = "IDLE", attention: int = 0, failed: int = 0):
    return build_ui_state(
        WorkerSnapshot(state, None, 0, None),
        QueueStats(
            pending=0,
            claimed=0,
            completed=215,
            needs_human=attention,
            retry=0,
            failed=failed,
        ),
    )


def test_status_tone_is_ready_when_queue_is_clean():
    assert _status_tone(_ui_state()) == "ready"


def test_status_tone_highlights_attention_and_failures():
    assert _status_tone(_ui_state(attention=1)) == "warning"
    assert _status_tone(_ui_state(state="FAILED", failed=1)) == "danger"
