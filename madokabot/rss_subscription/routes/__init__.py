from typing import List


def discover_route_modules() -> List[str]:
    from pathlib import Path

    module_paths = list(Path(__file__).parent.glob("*.py"))
    return [
        module.name[:-3]
        for module in module_paths
        if module.name != "__init__.py"
    ]


ROUTE_MODULES = sorted(discover_route_modules())
