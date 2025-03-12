import importlib
import inspect
import sys
from pathlib import Path
from types import ModuleType

# Directory where built-in handlers are stored
BUILTIN_DIR = Path(__file__).parent / "handlers"

# Ensure the built-in directory is in sys.path for import resolution
if str(BUILTIN_DIR) not in sys.path:
    sys.path.insert(0, str(BUILTIN_DIR))


def load_module(module_name: str, module_path: Path = None) -> ModuleType:
    """
    Dynamically loads a module from either built-in handlers or a user-provided path.

    Args:
        module_name (str): The name of the module.
        module_path (Path, optional): The path to the module. If None, it tries to load from built-in handlers.

    Returns:
        ModuleType: The loaded module.

    Raises:
        ImportError: If the module cannot be loaded.
        AttributeError: If the module does not have a valid 'execute' function.
        TypeError: If 'execute' does not have the correct function signature.
    """
    if module_path is None:
        module_path = BUILTIN_DIR / f"{module_name}.py"

    if not module_path.exists():
        raise ImportError(f"❌ Module '{module_name}' not found at {module_path}")

    spec = importlib.util.spec_from_file_location(module_name, str(module_path))
    if spec is None or spec.loader is None:
        raise ImportError(f"❌ Could not load module spec for '{module_name}'")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    # Verify the execute method presence
    validate_execute_method(module)

    return module


def validate_execute_method(module: ModuleType) -> None:
    """
    Validates that the loaded module has a valid 'execute' function.

    Args:
        module (ModuleType): The loaded module.

    Raises:
        AttributeError: If 'execute' function is missing.
        TypeError: If 'execute' does not have the correct function signature.
    """
    if not hasattr(module, "execute"):
        raise AttributeError(f"❌ Module '{module.__name__}' does not have an 'execute' function.")

    execute_func = module.execute
    signature = inspect.signature(execute_func)
    parameters = list(signature.parameters.values())

    # Check if the first parameter exists and is a string
    if len(parameters) < 1 or parameters[0].annotation is not str:
        raise TypeError(f"❌ 'execute' function in '{module.__name__}' must have a first parameter of type 'str'.")

    # Check if there is a second optional parameter, it must be a float
    if len(parameters) > 1:
        second_param = parameters[1]
        if second_param.default is not None and second_param.annotation is not float:
            raise TypeError(f"❌ 'execute' function in '{module.__name__}' must have an optional second parameter of type 'float'.")