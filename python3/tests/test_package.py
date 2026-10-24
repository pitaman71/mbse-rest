"""The package imports, beside mbse-schemas."""

import mbse.Services.Rest
from mbse.Schemas.Framework import Builders


def test_imports_beside_mbse_schemas():
    assert mbse.Services.Rest.__doc__
    assert Builders.Store() is not None
