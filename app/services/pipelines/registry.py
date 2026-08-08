"""Registry mapping declarative task types to executable handlers."""

from app.exceptions import UnknownTaskTypeError
from app.services.pipelines.handlers.base import TaskHandler
from app.services.pipelines.models import TaskType


class HandlerRegistry:
    """Mutable task handler registry populated at application composition."""

    def __init__(self, handlers: list[TaskHandler] | None = None) -> None:
        self._handlers: dict[TaskType, TaskHandler] = {}
        for handler in handlers or []:
            self.register(handler)

    def register(self, handler: TaskHandler) -> None:
        """Register or replace a handler for its declared task type."""
        self._handlers[handler.task_type] = handler

    def get(self, task_type: TaskType) -> TaskHandler:
        """Return handler for a task type or raise a domain error."""
        handler: TaskHandler | None = self._handlers.get(task_type)
        if handler is None:
            raise UnknownTaskTypeError(task_type)
        return handler
