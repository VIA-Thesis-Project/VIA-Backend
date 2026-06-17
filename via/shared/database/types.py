"""Custom SQLAlchemy column types used by VIA infrastructure models."""

from __future__ import annotations

from sqlalchemy.types import UserDefinedType


class Geometry(UserDefinedType):
    """PostGIS geometry type declaration without binding to a concrete adapter."""

    cache_ok = True

    def __init__(self, geometry_type: str, srid: int) -> None:
        self.geometry_type = geometry_type
        self.srid = srid

    def get_col_spec(self, **kwargs: object) -> str:
        """Return the PostgreSQL type name used in generated DDL."""

        return f"GEOMETRY({self.geometry_type}, {self.srid})"


class Vector(UserDefinedType):
    """pgvector type declaration with a fixed embedding dimension."""

    cache_ok = True

    def __init__(self, dimension: int) -> None:
        self.dimension = dimension

    def get_col_spec(self, **kwargs: object) -> str:
        """Return the PostgreSQL vector type specification."""

        return f"VECTOR({self.dimension})"
