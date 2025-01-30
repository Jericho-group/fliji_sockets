import inspect
from dataclasses import dataclass
from typing import Any, Dict, Callable, TypeVar

T = TypeVar('T')


@dataclass
class Context:
    sid: str
    # noinspection PyUnresolvedReferences
    app: 'SocketioApplication'


class DIContainer:
    def __init__(self):
        self._dependencies: Dict[str, Callable[..., T]] = {}
        self._instances: Dict[str, Any] = {}
        self._no_cache_keys = {"sio_session", "timeline_session", "timeline_group"}  # Always recreate

    def register(self, key: str, factory: Callable[..., T]) -> None:
        """Register a dependency factory function, allowing optional 'context'."""
        sig = inspect.signature(factory)
        params = list(sig.parameters.values())

        # Ensure factory has at most one argument, and it must be of type Context if present
        if len(params) > 1 or (params and params[0].annotation is not Context):
            raise TypeError(
                f"Factory function for '{key}' must accept zero or one argument of type 'Context'."
            )

        self._dependencies[key] = factory

    async def get(self, key: str, context: Context | None = None) -> Any:
        """Get or create an instance of a dependency, passing context if required"""

        # If the dependency is in the no-cache list, always create a new instance
        if key not in self._no_cache_keys and key in self._instances:
            return self._instances[key]

        factory = self._dependencies.get(key)
        if not factory:
            raise KeyError(f"No dependency registered for key: {key}")

        sig = inspect.signature(factory)
        params = sig.parameters

        # Call function with context only if it accepts it
        if context is not None and len(params) == 1:
            instance = await factory(context) if inspect.iscoroutinefunction(factory) else factory(
                context)
        else:
            instance = await factory() if inspect.iscoroutinefunction(factory) else factory()

        # Cache only if it's not in the no-cache list
        if key not in self._no_cache_keys:
            self._instances[key] = instance

        return instance

    def reset(self) -> None:
        """Clear all cached instances"""
        self._instances.clear()


# Global container instance
container = DIContainer()


def register_dependency(key: str):
    """Decorator to register a dependency factory"""

    def decorator(factory: Callable[..., T]) -> Callable[..., T]:
        container.register(key, factory)
        return factory

    return decorator


def Depends(dependency_key: str):
    """Dependency marker for injection"""
    return {"type": "dependency", "key": dependency_key}
