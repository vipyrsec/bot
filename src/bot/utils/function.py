"""Utilities for interaction with functions."""

import functools
import inspect
import types
from collections import OrderedDict
from collections.abc import Callable, Sequence
from typing import Any

from bot.log import get_logger

log = get_logger(__name__)

Argument = int | str
BoundArgs = OrderedDict[str, Any]
Decorator = Callable[[Callable], Callable]  # type: ignore[type-arg]
ArgValGetter = Callable[[BoundArgs], Any]


class GlobalNameConflictError(Exception):
    """Raised when there's a conflict between the globals used to resolve annotations of wrapped and its wrapper."""


def get_arg_value(name_or_pos: Argument, arguments: BoundArgs) -> Any:  # noqa: ANN401
    """
    Return a value from `arguments` based on a name or position.

    `arguments` is an ordered mapping of parameter names to argument values.

    Raise TypeError if `name_or_pos` isn't a str or int.
    Raise ValueError if `name_or_pos` does not match any argument.
    """
    if isinstance(name_or_pos, int):
        # Convert arguments to a tuple to make them indexable.
        arg_values = tuple(arguments.items())
        arg_pos = name_or_pos

        try:
            _name, value = arg_values[arg_pos]
        except IndexError as exception:
            msg = f"Argument position {arg_pos} is out of bounds."
            raise ValueError(msg) from exception
        else:
            return value
    elif isinstance(name_or_pos, str):
        arg_name = name_or_pos
        try:
            return arguments[arg_name]
        except KeyError as exception:
            msg = f"Argument {arg_name!r} doesn't exist."
            raise ValueError(msg) from exception
    else:
        msg = "'arg' must either be an int (positional index) or a str (keyword)."
        raise TypeError(msg)


def get_arg_value_wrapper(
    decorator_func: Callable[[ArgValGetter], Decorator],
    name_or_pos: Argument,
    func: Callable[[Any], Any] | None = None,
) -> Decorator:
    """
    Call `decorator_func` with the value of the arg at the given name/position.

    `decorator_func` must accept a callable as a parameter to which it will pass a mapping of
    parameter names to argument values of the function it's decorating.

    `func` is an optional callable which will return a new value given the argument's value.

    Return the decorator returned by `decorator_func`.
    """

    def wrapper(args: BoundArgs) -> Any:  # noqa: ANN401
        value = get_arg_value(name_or_pos, args)
        if func:
            value = func(value)
        return value

    return decorator_func(wrapper)


def get_bound_args(func: Callable, args: tuple, kwargs: dict[str, Any]) -> BoundArgs:  # type: ignore[type-arg]
    """
    Bind `args` and `kwargs` to `func` and return a mapping of parameter names to argument values.

    Default parameter values are also set.
    """
    sig = inspect.signature(func)
    bound_args = sig.bind(*args, **kwargs)
    bound_args.apply_defaults()

    return bound_args.arguments


def update_wrapper_globals(
    wrapper: types.FunctionType,
    wrapped: types.FunctionType,
    *,
    ignored_conflict_names: set[str] = frozenset(),  # type: ignore[assignment]
) -> types.FunctionType:
    """
    Update globals of `wrapper` with the globals from `wrapped`.

    For forwardrefs in command annotations discordpy uses the __global__ attribute of the function
    to resolve their values, with decorators that replace the function this breaks because they have
    their own globals.

    This function creates a new function functionally identical to `wrapper`, which has the globals replaced with
    a merge of `wrapped`s globals and the `wrapper`s globals.

    An exception will be raised in case `wrapper` and `wrapped` share a global name that is used by
    `wrapped`'s typehints and is not in `ignored_conflict_names`,
    as this can cause incorrect objects being used by discordpy's converters.
    """
    annotation_global_names = (
        ann.split(".", maxsplit=1)[0] for ann in wrapped.__annotations__.values() if isinstance(ann, str)
    )
    # Conflicting globals from both functions' modules that are also used in the wrapper and in wrapped's annotations.
    shared_globals = set(wrapper.__code__.co_names) & set(annotation_global_names)
    shared_globals &= set(wrapped.__globals__) & set(wrapper.__globals__) - ignored_conflict_names
    if shared_globals:
        msg = (
            f"wrapper and the wrapped function share the following global names used by annotations: {', '.join(shared_globals)}."  # noqa: E501
            "Resolve the conflicts or add the name to the `ignored_conflict_names` set to suppress this error if this is intentional."  # noqa: E501
        )
        raise GlobalNameConflictError(msg)

    new_globals = wrapper.__globals__.copy()
    new_globals.update((k, v) for k, v in wrapped.__globals__.items() if k not in wrapper.__code__.co_names)
    return types.FunctionType(
        code=wrapper.__code__,
        globals=new_globals,
        name=wrapper.__name__,
        argdefs=wrapper.__defaults__,
        closure=wrapper.__closure__,
    )


def command_wraps(
    wrapped: types.FunctionType,
    assigned: Sequence[str] = functools.WRAPPER_ASSIGNMENTS,
    updated: Sequence[str] = functools.WRAPPER_UPDATES,
    *,
    ignored_conflict_names: set[str] = frozenset(),  # type: ignore[assignment]
) -> Callable[[types.FunctionType], types.FunctionType]:
    """Update the decorated function to look like `wrapped` and update globals for discordpy forwardref evaluation."""

    def decorator(wrapper: types.FunctionType) -> types.FunctionType:
        return functools.update_wrapper(  # type: ignore[return-value]
            update_wrapper_globals(wrapper, wrapped, ignored_conflict_names=ignored_conflict_names),
            wrapped,
            assigned,
            updated,
        )

    return decorator
