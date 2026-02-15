# SPDX-License-Identifier: Apache-2.0

import sys

from tools.error_dictionary import ErrorDictionary, install_global_excepthook
from tools.interactive_onboarding import OnboardingGuide


def test_error_dictionary_lookup() -> None:
    err = ErrorDictionary.get_error("E301")
    assert err is not None
    assert err.code == "E301"


def test_error_dictionary_suggestion() -> None:
    err = ErrorDictionary.suggest_error("Replay baseline mismatch detected")
    assert err is not None
    assert err.code == "E301"


def test_install_global_excepthook_sets_handler() -> None:
    original = sys.excepthook
    try:
        install_global_excepthook()
        assert sys.excepthook == ErrorDictionary.handle_exception
    finally:
        sys.excepthook = original


def test_onboarding_additional_checks_return_tuple() -> None:
    checks = [
        OnboardingGuide.check_port_8080_available,
        OnboardingGuide.check_disk_space,
        OnboardingGuide.check_git_integrity,
    ]
    for fn in checks:
        ok, detail = fn()
        assert isinstance(ok, bool)
        assert isinstance(detail, str)
