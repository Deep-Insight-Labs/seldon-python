"""Explicit Seldon Functions. Imports create no clients and load no application files."""

__version__ = "0.1.0.dev1"


def function(**settings):
    from .decorator import function as decorate

    return decorate(**settings)


def configure(**settings):
    from .runtime import configure as apply

    apply(**settings)


def __getattr__(name):
    if name in {"CallInfo", "close", "aclose"}:
        from . import runtime

        return getattr(runtime, name)
    raise AttributeError(name)
