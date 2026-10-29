"""Offline geographic ordering for German postcodes."""

from __future__ import annotations

import csv
import math
from pathlib import Path


class PostcodeCoordinateIndex:
    """German postcode centroids with deterministic nearest-neighbour lookup.

    Coordinates identify postcode centroids, so distances are suitable for
    search expansion ordering rather than parcel-level valuation.
    """

    def __init__(self, coordinates: dict[str, tuple[float, float]]) -> None:
        self._coordinates = dict(coordinates)

    @classmethod
    def from_csv(cls, path: str | Path) -> "PostcodeCoordinateIndex":
        coordinates: dict[str, tuple[float, float]] = {}
        with Path(path).open(encoding="utf-8", newline="") as source:
            reader = csv.reader(source)
            next(reader, None)
            for row in reader:
                if len(row) < 3:
                    continue
                postcode = row[0].strip().zfill(5)
                try:
                    coordinates[postcode] = (float(row[1]), float(row[2]))
                except ValueError:
                    continue
        return cls(coordinates)

    @classmethod
    def empty(cls) -> "PostcodeCoordinateIndex":
        return cls({})

    def nearby_postcodes(
        self,
        postcode: str | None,
        *,
        maximum_distance_km: float = 25.0,
        limit: int = 5,
    ) -> list[str]:
        """Return nearby postcodes ordered by centroid distance.

        Missing or unknown postcodes safely produce no expansion candidates.
        """

        if not postcode or limit <= 0 or maximum_distance_km <= 0:
            return []
        subject = self._coordinates.get(postcode)
        if subject is None:
            return []
        nearby = [
            (self._distance_km(subject, coordinates), candidate)
            for candidate, coordinates in self._coordinates.items()
            if candidate != postcode
        ]
        return [
            candidate
            for distance, candidate in sorted(nearby)
            if distance <= maximum_distance_km
        ][:limit]

    def distance_between_postcodes(
        self, first_postcode: str | None, second_postcode: str | None
    ) -> float | None:
        """Return centroid distance in kilometres when both postcodes are known."""

        if not first_postcode or not second_postcode:
            return None
        first = self._coordinates.get(first_postcode)
        second = self._coordinates.get(second_postcode)
        if first is None or second is None:
            return None
        return round(self._distance_km(first, second), 1)

    def coordinates_for(self, postcode: str | None) -> tuple[float, float] | None:
        """Return the locally stored centroid for an exact postcode."""

        if not postcode:
            return None
        return self._coordinates.get(postcode)

    @staticmethod
    def _distance_km(
        first: tuple[float, float], second: tuple[float, float]
    ) -> float:
        lat1, lon1 = map(math.radians, first)
        lat2, lon2 = map(math.radians, second)
        haversine = (
            math.sin((lat2 - lat1) / 2) ** 2
            + math.cos(lat1)
            * math.cos(lat2)
            * math.sin((lon2 - lon1) / 2) ** 2
        )
        return 6371.0088 * 2 * math.asin(math.sqrt(haversine))
