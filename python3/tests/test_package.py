"""The package imports, beside mbse-schemas."""

import mbse.Rest
from mbse.Schemas.Framework import Builders


def test_imports_beside_mbse_schemas():
    assert mbse.Rest.__doc__
    assert Builders.Store() is not None
