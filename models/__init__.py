from pathlib import Path
from importlib import import_module

# 自动导入所有模型模块
__all__ = []
for path in Path(__file__).parent.rglob("*.py"):
    if path.name.startswith("_"):
        continue
    module_name = path.with_suffix("").name
    __all__.append(module_name)
    import_module(f".{module_name}", __name__)
