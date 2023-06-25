"""Custom Exception(s)"""

from collections.abc import Hashable


class APIError(Exception):
    """Raised when an external API (eg. Wikipedia) returns an error response."""

    def __init__(self, api: str, status_code: int, error_msg: str | None = None):
        super().__init__()
        self.api = api
        self.status_code = status_code
        self.error_msg = error_msg


class MovedCommandError(Exception):
    """Raised when a command has moved locations."""

    def __init__(self, new_command_name: str):
        self.new_command_name = new_command_name


class LockedResourceError(RuntimeError):
    """
    Exception raised when an operation is attempted on a locked resource.

    Attributes:
        `type` -- name of the locked resource's type
        `id` -- ID of the locked resource
    """

    def __init__(self, resource_type: str, resource_id: Hashable):
        self.type = resource_type
        self.id = resource_id

        super().__init__(
            f"Cannot operate on {self.type.lower()} `{self.id}`; "
            "it is currently locked and in use by another operation."
        )
