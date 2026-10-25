from propertyscout.postcode_proximity import PostcodeCoordinateIndex


def test_postcode_index_orders_by_geographic_distance(tmp_path) -> None:
    source = tmp_path / "postcodes.csv"
    source.write_text(
        ",lat,lng\n10000,52.0,13.0\n10001,52.01,13.0\n10002,52.10,13.0\n",
        encoding="utf-8",
    )

    index = PostcodeCoordinateIndex.from_csv(source)

    assert index.nearby_postcodes("10000", maximum_distance_km=20, limit=2) == [
        "10001",
        "10002",
    ]
    assert index.distance_between_postcodes("10000", "10001") is not None


def test_postcode_index_does_not_expand_unknown_postcodes() -> None:
    assert PostcodeCoordinateIndex.empty().nearby_postcodes("10000") == []
