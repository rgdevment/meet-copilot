import importlib
import sys

MIN_PYTHON = (3, 10)

CORE_MODULES = {
    "openai": "openai",
    "anthropic": "anthropic",
    "google.generativeai": "google-generativeai",
    "deep_translator": "deep-translator",
    "customtkinter": "customtkinter",
}

PLATFORM_MODULES = {
    "win32": {"uiautomation": "uiautomation"},
    "darwin": {
        "ApplicationServices": "pyobjc-framework-ApplicationServices",
        "Quartz": "pyobjc-framework-Quartz",
    },
}


def main() -> int:
    problems = []

    if sys.version_info < MIN_PYTHON:
        found = f"{sys.version_info.major}.{sys.version_info.minor}"
        problems.append(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required, found {found}")

    required = dict(CORE_MODULES)
    required.update(PLATFORM_MODULES.get(sys.platform, {}))

    for module, package in required.items():
        try:
            importlib.import_module(module)
        except ImportError:
            problems.append(f"missing package: {package} (import '{module}')")

    if problems:
        print("[doctor] environment NOT ready:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print("[doctor] environment ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())
