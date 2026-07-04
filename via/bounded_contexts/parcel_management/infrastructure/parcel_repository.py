"""SQLAlchemy parcel repository adapter."""

from __future__ import annotations

import struct
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from via.bounded_contexts.parcel_management.application.ports import IParcelRepository
from via.bounded_contexts.parcel_management.domain.parcel import Parcel
from via.bounded_contexts.parcel_management.domain.value_objects import GeoJSONGeometry, ParcelMetadata
from via.bounded_contexts.parcel_management.infrastructure.orm_models import ParcelModel, ParcelVersionModel


class SQLAlchemyParcelRepository(IParcelRepository):
    """Persist parcels in the transactional schema using PostGIS geometry columns."""

    def __init__(self, session: Session) -> None:
        """Create the repository bound to a synchronous SQLAlchemy session."""

        self._session = session

    def add(self, parcel: Parcel) -> None:
        """Persist a new parcel without committing the transaction."""

        model = _to_model(parcel)
        self._session.add(model)
        self._session.flush()
        self._session.refresh(model)
        parcel.created_at = model.created_at

    def get_by_id(self, parcel_id: UUID) -> Parcel | None:
        """Return one parcel by id regardless of owner."""

        model = self._session.get(ParcelModel, parcel_id)
        return _to_domain(model) if model is not None else None

    def list_by_owner(self, owner_id: UUID) -> list[Parcel]:
        """Return parcels owned by a user."""

        statement = (
            select(ParcelModel)
            .where(ParcelModel.owner_id == owner_id)
            .order_by(ParcelModel.created_at.desc())
        )
        return [_to_domain(model) for model in self._session.execute(statement).scalars().all()]

    def save(self, parcel: Parcel) -> None:
        """Persist updates to an existing parcel without committing."""

        model = self._session.get(ParcelModel, parcel.id)
        if model is None:
            self.add(parcel)
            return
        model.geometry = geojson_multipolygon_to_wkt(parcel.geometry)
        model.metadata_json = parcel.metadata.to_mapping()

    def record_version_snapshot(self, parcel: Parcel) -> None:
        """Store a snapshot of current parcel state before mutation."""

        self._session.add(
            ParcelVersionModel(
                parcel_id=parcel.id,
                metadata_snapshot=parcel.metadata.to_mapping(),
                geometry_snapshot=geojson_multipolygon_to_wkt(parcel.geometry),
            )
        )


def _to_model(parcel: Parcel) -> ParcelModel:
    return ParcelModel(
        id=parcel.id,
        owner_id=parcel.owner_id,
        geometry=geojson_multipolygon_to_wkt(parcel.geometry),
        metadata_json=parcel.metadata.to_mapping(),
    )


def _to_domain(model: ParcelModel) -> Parcel:
    return Parcel(
        id=model.id,
        owner_id=model.owner_id,
        geometry=wkt_to_geojson_multipolygon(model.geometry),
        metadata=ParcelMetadata.from_mapping(model.metadata_json),
        created_at=model.created_at,
    )


def geojson_multipolygon_to_wkt(geometry: GeoJSONGeometry) -> str:
    """Serialize normalized GeoJSON MultiPolygon to EWKT for SRID 4326."""

    polygons = []
    for polygon in geometry.coordinates:
        rings = []
        for ring in polygon:
            points = ", ".join(f"{float(point[0])} {float(point[1])}" for point in ring)
            rings.append(f"({points})")
        polygons.append(f"({', '.join(rings)})")
    return f"SRID=4326;MULTIPOLYGON({', '.join(polygons)})"


def wkt_to_geojson_multipolygon(value: object) -> GeoJSONGeometry:
    """Deserialize supported geometry representations to GeoJSONGeometry.

    Accepts GeoJSONGeometry, GeoJSON dict, EWKT/WKT text, binary EWKB (bytes /
    memoryview), and EWKB/WKB hex strings as returned by PostGIS via psycopg2
    when no explicit type adapter is registered.
    """

    if isinstance(value, GeoJSONGeometry):
        return value
    if isinstance(value, dict):
        return GeoJSONGeometry.from_geojson(value)
    if isinstance(value, (bytes, memoryview)):
        return _ewkb_bytes_to_geojson_multipolygon(bytes(value))
    text = str(value).strip()
    if _is_ewkb_hex(text):
        return _ewkb_bytes_to_geojson_multipolygon(bytes.fromhex(text))
    if text.startswith("SRID=4326;"):
        text = text.split(";", 1)[1]
    if not text.startswith("MULTIPOLYGON"):
        raise ValueError("Stored parcel geometry must be MULTIPOLYGON")
    body = text[len("MULTIPOLYGON") :].strip()
    return GeoJSONGeometry(coordinates=_parse_multipolygon_body(body))


def _is_ewkb_hex(text: str) -> bool:
    """Return True when text looks like a hex-encoded WKB/EWKB geometry blob.

    PostGIS returns geometry columns as hex EWKB text via psycopg2 when no
    explicit type adapter is registered.  Such strings always start with a
    byte-order indicator (01 = little-endian, 00 = big-endian) and consist
    entirely of hexadecimal characters.
    """
    if len(text) < 10 or len(text) % 2 != 0:
        return False
    if text[:2].lower() not in ("01", "00"):
        return False
    return all(c in "0123456789abcdefABCDEF" for c in text)


def _ewkb_bytes_to_geojson_multipolygon(data: bytes) -> GeoJSONGeometry:
    """Decode EWKB/WKB binary into a GeoJSONGeometry(MultiPolygon).

    Handles PostGIS EWKB with or without embedded SRID, with or without Z/M
    coordinate dimensions.  Uses only the Python standard-library `struct`
    module — no Shapely or GeoAlchemy2 required.
    """
    offset = 0

    byte_order = data[offset]
    offset += 1
    endian = "<" if byte_order == 1 else ">"

    (raw_type,) = struct.unpack_from(f"{endian}I", data, offset)
    offset += 4

    has_srid = bool(raw_type & 0x20000000)
    has_z    = bool(raw_type & 0x80000000)
    has_m    = bool(raw_type & 0x40000000)
    geom_type = raw_type & 0x0000FFFF

    if geom_type != 6:
        raise ValueError(
            f"Stored parcel geometry must be MULTIPOLYGON (WKB type 6),"
            f" got WKB type {geom_type}"
        )

    if has_srid:
        offset += 4

    (num_polygons,) = struct.unpack_from(f"{endian}I", data, offset)
    offset += 4

    polygons = []
    for _ in range(num_polygons):
        sub_byte_order = data[offset]
        offset += 1
        sub_endian = "<" if sub_byte_order == 1 else ">"

        (sub_raw_type,) = struct.unpack_from(f"{sub_endian}I", data, offset)
        offset += 4
        sub_has_srid = bool(sub_raw_type & 0x20000000)
        sub_has_z    = bool(sub_raw_type & 0x80000000)
        sub_has_m    = bool(sub_raw_type & 0x40000000)

        if sub_has_srid:
            offset += 4

        (num_rings,) = struct.unpack_from(f"{sub_endian}I", data, offset)
        offset += 4

        rings = []
        for _ in range(num_rings):
            (num_points,) = struct.unpack_from(f"{sub_endian}I", data, offset)
            offset += 4
            points = []
            for _ in range(num_points):
                (x,) = struct.unpack_from(f"{sub_endian}d", data, offset)
                offset += 8
                (y,) = struct.unpack_from(f"{sub_endian}d", data, offset)
                offset += 8
                if sub_has_z:
                    offset += 8
                if sub_has_m:
                    offset += 8
                points.append([x, y])
            rings.append(points)
        polygons.append(rings)

    return GeoJSONGeometry(coordinates=polygons)


def _parse_multipolygon_body(body: str) -> list:
    content = body.strip()[1:-1]
    polygons = []
    for polygon_text in _split_top_level(content):
        polygon_content = polygon_text.strip()[1:-1]
        rings = []
        for ring_text in _split_top_level(polygon_content):
            ring_content = ring_text.strip()[1:-1]
            points = []
            for point_text in ring_content.split(","):
                x_text, y_text = point_text.strip().split()[:2]
                points.append([float(x_text), float(y_text)])
            rings.append(points)
        polygons.append(rings)
    return polygons


def _split_top_level(text: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    start = 0
    for index, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(text[start:index].strip())
            start = index + 1
    parts.append(text[start:].strip())
    return [part for part in parts if part]
