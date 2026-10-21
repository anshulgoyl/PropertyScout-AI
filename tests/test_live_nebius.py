import os

import pytest

from propertyscout.analyst import analyse_property, create_nebius_reasoner
from propertyscout.bootstrap import default_criteria
from propertyscout.fixtures import sample_properties


@pytest.mark.live
@pytest.mark.skipif(not os.getenv("NEBIUS_API_KEY"), reason="NEBIUS_API_KEY is not configured")
def test_nebius_returns_a_valid_structured_judgment() -> None:
    analysis = analyse_property(
        sample_properties()["shortlist"],
        default_criteria(),
        create_nebius_reasoner(),
    )

    assert analysis.thesis
    assert analysis.risks
