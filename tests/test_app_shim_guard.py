# SPDX-License-Identifier: Apache-2.0

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

pytestmark = pytest.mark.regression_standard


def test_app_compatibility_shims_have_no_logic() -> None:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "check_app_shims.py"
    spec = spec_from_file_location("check_app_shims", script_path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main() == 0
