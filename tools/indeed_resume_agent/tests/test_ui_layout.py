from tools.indeed_resume_agent.ui_v2 import _layout_for_width


def test_wide_layout_keeps_actions_readable_without_overstretching():
    layout = _layout_for_width(1366)

    assert layout.metric_columns == 3
    assert layout.sync_columns == 2
    assert layout.operation_columns == 3
    assert layout.max_content_width == 1120
    assert layout.shell_padding == 20


def test_compact_layout_stacks_primary_actions_and_operation_buttons():
    layout = _layout_for_width(840)

    assert layout.metric_columns == 2
    assert layout.sync_columns == 1
    assert layout.operation_columns == 2
    assert layout.max_content_width == 840
    assert layout.shell_padding == 12


def test_narrow_layout_uses_single_column_actions_without_losing_labels():
    layout = _layout_for_width(720)

    assert layout.metric_columns == 2
    assert layout.sync_columns == 1
    assert layout.operation_columns == 1
    assert layout.max_content_width == 720
    assert layout.shell_padding == 10
