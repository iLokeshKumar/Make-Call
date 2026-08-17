import importlib.util
import sys
from pathlib import Path

import pytest


_MODULE_PATH = Path(__file__).parents[1] / "services" / "ai" / "llm" / "airllm_provider.py"
_SPEC = importlib.util.spec_from_file_location("airllm_provider_under_test", _MODULE_PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
_install_bettertransformer_compat_shim = _MODULE._install_bettertransformer_compat_shim


def test_bettertransformer_shim_triggers_airllm_sdpa_fallback():
    previous = sys.modules.get("optimum.bettertransformer")
    try:
        _install_bettertransformer_compat_shim()
        module = sys.modules["optimum.bettertransformer"]

        with pytest.raises(ValueError, match="native SDPA"):
            module.BetterTransformer.transform(object())
    finally:
        if previous is None:
            sys.modules.pop("optimum.bettertransformer", None)
        else:
            sys.modules["optimum.bettertransformer"] = previous
