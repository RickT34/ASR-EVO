from __future__ import annotations

import pytest

from asr_evo.core.tray_proxy import UnboundStatusTray


def test_unbound_status_tray_reports_missing_binding() -> None:
    tray = UnboundStatusTray()

    with pytest.raises(RuntimeError, match="status tray has not been bound"):
        tray.set_state("idle")
