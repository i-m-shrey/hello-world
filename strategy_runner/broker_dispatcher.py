import os
import sys
import importlib.util


def _load_module_by_path(module_name: str, file_path: str):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load spec for {module_name} at {file_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def get_executor_for_broker(broker_name: str):
    name = broker_name.strip().upper()
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    if name == "FINVASIA":
        file_path = os.path.join(script_dir, "finvasia_broker_api.py")
        return _load_module_by_path("finvasia_broker_api", file_path)
    
    elif name == "DHAN":
        file_path = os.path.join(script_dir, "dhan_broker_api.py")
        return _load_module_by_path("dhan_broker_api", file_path)
    
    elif name == "ZERODHA":
        file_path = os.path.join(script_dir, "zerodha_broker_api.py")
        return _load_module_by_path("zerodha_broker_api", file_path)
    
    elif name == "MSTOCK":
        file_path = os.path.join(script_dir, "mstock_executor.py")
        return _load_module_by_path("mstock_executor", file_path)
    
    elif name == "ICICI":
        file_path = os.path.join(script_dir, "icici_executor.py")
        return _load_module_by_path("icici_executor", file_path)
    
    elif name == "HDFC":
        file_path = os.path.join(script_dir, "hdfc_executor.py")
        return _load_module_by_path("hdfc_executor", file_path)
    
    elif name in ("ANGEL", "ANGELONE", "ANGLE", "ANGEL ONE", "ANGELBROKING"):
        file_path = os.path.join(script_dir, "angel_broker_api.py")
        return _load_module_by_path("angel_broker_api", file_path)

    else:
        raise ValueError(f"Unsupported broker: {broker_name}")
