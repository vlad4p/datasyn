"""Project resources."""

from .database import database_resource

resources = {"database": database_resource}

__all__ = ["database_resource", "resources"]
