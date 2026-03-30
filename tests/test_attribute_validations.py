"""Tests for attribute-level validation of product values.

When a product is created or patched, its values are validated against the
attribute definitions (max_characters, validation_regexp, number_min/max,
decimals_allowed, negative_allowed, date_min/date_max).
"""

from fastapi.testclient import TestClient
from akeneo_mock_server.app import app

client = TestClient(app)


def _create_attribute(code: str, attr_type: str, **extra):
    payload = {"code": code, "type": attr_type, "group": "other", **extra}
    res = client.post("/api/rest/v1/attributes", json=payload)
    assert res.status_code == 201, f"Failed to create attribute {code!r}: {res.text}"
    return res


def _create_product(identifier: str, values: dict):
    return client.post(
        "/api/rest/v1/products",
        json={"identifier": identifier, "values": values},
    )


def _value(data):
    """Wrap a value in the standard locale/scope envelope."""
    return [{"locale": None, "scope": None, "data": data}]


# ---------------------------------------------------------------------------
# max_characters
# ---------------------------------------------------------------------------


class TestMaxCharacters:
    def test_text_value_exceeding_max_characters_returns_422(self):
        _create_attribute("short_text_1", "pim_catalog_text", max_characters=5)
        res = _create_product("p-maxchar-1", {"short_text_1": _value("toolong")})
        assert res.status_code == 422

    def test_text_value_within_max_characters_succeeds(self):
        _create_attribute("short_text_2", "pim_catalog_text", max_characters=10)
        res = _create_product("p-maxchar-2", {"short_text_2": _value("hi")})
        assert res.status_code == 201

    def test_text_value_at_exactly_max_characters_succeeds(self):
        _create_attribute("exact_text_3", "pim_catalog_text", max_characters=5)
        res = _create_product("p-maxchar-3", {"exact_text_3": _value("hello")})
        assert res.status_code == 201

    def test_textarea_value_exceeding_max_characters_returns_422(self):
        _create_attribute("short_area_4", "pim_catalog_textarea", max_characters=10)
        res = _create_product("p-maxchar-4", {"short_area_4": _value("this is way too long")})
        assert res.status_code == 422

    def test_patch_with_value_exceeding_max_characters_returns_422(self):
        _create_attribute("patch_text_5", "pim_catalog_text", max_characters=5)
        client.post("/api/rest/v1/products", json={"identifier": "p-maxchar-patch"})
        res = client.patch(
            "/api/rest/v1/products/p-maxchar-patch",
            json={"values": {"patch_text_5": _value("toolong")}},
        )
        assert res.status_code == 422

    def test_no_max_characters_allows_any_length(self):
        _create_attribute("free_length_6", "pim_catalog_text")
        res = _create_product("p-maxchar-6", {"free_length_6": _value("x" * 500)})
        assert res.status_code == 201


# ---------------------------------------------------------------------------
# validation_rule / validation_regexp
# ---------------------------------------------------------------------------


class TestValidationRegexp:
    def test_value_not_matching_regexp_returns_422(self):
        _create_attribute(
            "digits_only_1",
            "pim_catalog_text",
            validation_rule="regexp",
            validation_regexp="^[0-9]+$",
        )
        res = _create_product("p-regexp-1", {"digits_only_1": _value("abc")})
        assert res.status_code == 422

    def test_value_matching_regexp_succeeds(self):
        _create_attribute(
            "digits_only_2",
            "pim_catalog_text",
            validation_rule="regexp",
            validation_regexp="^[0-9]+$",
        )
        res = _create_product("p-regexp-2", {"digits_only_2": _value("12345")})
        assert res.status_code == 201

    def test_regexp_on_identifier_attribute_type_returns_422(self):
        _create_attribute(
            "sku_pattern_3",
            "pim_catalog_identifier",
            validation_rule="regexp",
            validation_regexp="^SKU-[0-9]+$",
        )
        res = _create_product("p-regexp-3", {"sku_pattern_3": _value("INVALID")})
        assert res.status_code == 422

    def test_no_validation_rule_skips_regexp_check(self):
        _create_attribute("free_text_4", "pim_catalog_text")
        res = _create_product("p-regexp-4", {"free_text_4": _value("anything goes!")})
        assert res.status_code == 201

    def test_patch_value_not_matching_regexp_returns_422(self):
        _create_attribute(
            "alpha_only_5",
            "pim_catalog_text",
            validation_rule="regexp",
            validation_regexp="^[a-z]+$",
        )
        client.post("/api/rest/v1/products", json={"identifier": "p-regexp-patch"})
        res = client.patch(
            "/api/rest/v1/products/p-regexp-patch",
            json={"values": {"alpha_only_5": _value("123")}},
        )
        assert res.status_code == 422


# ---------------------------------------------------------------------------
# number_min
# ---------------------------------------------------------------------------


class TestNumberMin:
    def test_value_below_number_min_returns_422(self):
        _create_attribute("qty_1", "pim_catalog_number", number_min="10")
        res = _create_product("p-nummin-1", {"qty_1": _value("5")})
        assert res.status_code == 422

    def test_value_at_number_min_succeeds(self):
        _create_attribute("qty_2", "pim_catalog_number", number_min="10")
        res = _create_product("p-nummin-2", {"qty_2": _value("10")})
        assert res.status_code == 201

    def test_value_above_number_min_succeeds(self):
        _create_attribute("qty_3", "pim_catalog_number", number_min="0")
        res = _create_product("p-nummin-3", {"qty_3": _value("42")})
        assert res.status_code == 201


# ---------------------------------------------------------------------------
# number_max
# ---------------------------------------------------------------------------


class TestNumberMax:
    def test_value_above_number_max_returns_422(self):
        _create_attribute("score_1", "pim_catalog_number", number_max="100")
        res = _create_product("p-nummax-1", {"score_1": _value("150")})
        assert res.status_code == 422

    def test_value_at_number_max_succeeds(self):
        _create_attribute("score_2", "pim_catalog_number", number_max="100")
        res = _create_product("p-nummax-2", {"score_2": _value("100")})
        assert res.status_code == 201

    def test_value_below_number_max_succeeds(self):
        _create_attribute("score_3", "pim_catalog_number", number_max="100")
        res = _create_product("p-nummax-3", {"score_3": _value("50")})
        assert res.status_code == 201


# ---------------------------------------------------------------------------
# decimals_allowed
# ---------------------------------------------------------------------------


class TestDecimalsAllowed:
    def test_decimal_value_when_not_allowed_returns_422(self):
        _create_attribute("int_num_1", "pim_catalog_number", decimals_allowed=False)
        res = _create_product("p-dec-1", {"int_num_1": _value("3.14")})
        assert res.status_code == 422

    def test_integer_value_when_decimals_not_allowed_succeeds(self):
        _create_attribute("int_num_2", "pim_catalog_number", decimals_allowed=False)
        res = _create_product("p-dec-2", {"int_num_2": _value("3")})
        assert res.status_code == 201

    def test_decimal_value_when_allowed_succeeds(self):
        _create_attribute("float_num_3", "pim_catalog_number", decimals_allowed=True)
        res = _create_product("p-dec-3", {"float_num_3": _value("3.14")})
        assert res.status_code == 201

    def test_integer_as_float_string_when_not_allowed_succeeds(self):
        """3.0 is numerically an integer even if written with decimal point."""
        _create_attribute("int_num_4", "pim_catalog_number", decimals_allowed=False)
        res = _create_product("p-dec-4", {"int_num_4": _value("5.0")})
        assert res.status_code == 201


# ---------------------------------------------------------------------------
# negative_allowed
# ---------------------------------------------------------------------------


class TestNegativeAllowed:
    def test_negative_value_when_not_allowed_returns_422(self):
        _create_attribute("pos_num_1", "pim_catalog_number", negative_allowed=False)
        res = _create_product("p-neg-1", {"pos_num_1": _value("-5")})
        assert res.status_code == 422

    def test_zero_when_negatives_not_allowed_succeeds(self):
        _create_attribute("pos_num_2", "pim_catalog_number", negative_allowed=False)
        res = _create_product("p-neg-2", {"pos_num_2": _value("0")})
        assert res.status_code == 201

    def test_positive_value_when_negatives_not_allowed_succeeds(self):
        _create_attribute("pos_num_3", "pim_catalog_number", negative_allowed=False)
        res = _create_product("p-neg-3", {"pos_num_3": _value("5")})
        assert res.status_code == 201

    def test_negative_value_when_allowed_succeeds(self):
        _create_attribute("any_num_4", "pim_catalog_number", negative_allowed=True)
        res = _create_product("p-neg-4", {"any_num_4": _value("-5")})
        assert res.status_code == 201


# ---------------------------------------------------------------------------
# date_min
# ---------------------------------------------------------------------------


class TestDateMin:
    def test_date_before_min_returns_422(self):
        _create_attribute("release_1", "pim_catalog_date", date_min="2020-01-01T00:00:00")
        res = _create_product("p-datemin-1", {"release_1": _value("2019-06-15T00:00:00")})
        assert res.status_code == 422

    def test_date_at_min_succeeds(self):
        _create_attribute("release_2", "pim_catalog_date", date_min="2020-01-01T00:00:00")
        res = _create_product("p-datemin-2", {"release_2": _value("2020-01-01T00:00:00")})
        assert res.status_code == 201

    def test_date_after_min_succeeds(self):
        _create_attribute("release_3", "pim_catalog_date", date_min="2020-01-01T00:00:00")
        res = _create_product("p-datemin-3", {"release_3": _value("2021-06-15T00:00:00")})
        assert res.status_code == 201


# ---------------------------------------------------------------------------
# date_max
# ---------------------------------------------------------------------------


class TestDateMax:
    def test_date_after_max_returns_422(self):
        _create_attribute("expiry_1", "pim_catalog_date", date_max="2020-12-31T23:59:59")
        res = _create_product("p-datemax-1", {"expiry_1": _value("2021-06-15T00:00:00")})
        assert res.status_code == 422

    def test_date_at_max_succeeds(self):
        _create_attribute("expiry_2", "pim_catalog_date", date_max="2020-12-31T23:59:59")
        res = _create_product("p-datemax-2", {"expiry_2": _value("2020-12-31T23:59:59")})
        assert res.status_code == 201

    def test_date_before_max_succeeds(self):
        _create_attribute("expiry_3", "pim_catalog_date", date_max="2020-12-31T23:59:59")
        res = _create_product("p-datemax-3", {"expiry_3": _value("2020-06-15T00:00:00")})
        assert res.status_code == 201


# ---------------------------------------------------------------------------
# edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_unknown_attribute_skips_validation(self):
        """Values for attributes not in DB should be accepted without error."""
        res = _create_product("p-unknown-attr", {"nonexistent_attr": _value("any value")})
        assert res.status_code == 201

    def test_null_value_skips_validation(self):
        """A null data value should not trigger max_characters validation."""
        _create_attribute("null_text", "pim_catalog_text", max_characters=5)
        res = _create_product(
            "p-nullval",
            {"null_text": [{"locale": None, "scope": None, "data": None}]},
        )
        assert res.status_code == 201

    def test_number_min_and_max_combined(self):
        """A value between min and max should be accepted."""
        _create_attribute("range_num", "pim_catalog_number", number_min="0", number_max="100")
        res = _create_product("p-range-ok", {"range_num": _value("50")})
        assert res.status_code == 201

    def test_number_below_combined_min_returns_422(self):
        _create_attribute("range_num2", "pim_catalog_number", number_min="0", number_max="100")
        res = _create_product("p-range-low", {"range_num2": _value("-1")})
        assert res.status_code == 422

    def test_number_above_combined_max_returns_422(self):
        _create_attribute("range_num3", "pim_catalog_number", number_min="0", number_max="100")
        res = _create_product("p-range-high", {"range_num3": _value("101")})
        assert res.status_code == 422
