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


# ---------------------------------------------------------------------------
# Data-type format restrictions (per products.md "The data format" section)
# ---------------------------------------------------------------------------


def _patch_product(identifier: str, values: dict):
    return client.patch(
        f"/api/rest/v1/products/{identifier}",
        json={"values": values},
    )


class TestTextFormatRestriction:
    def test_non_string_data_for_text_returns_422(self):
        _create_attribute("text_fmt_1", "pim_catalog_text")
        res = _create_product("p-textfmt-1", {"text_fmt_1": _value(42)})
        assert res.status_code == 422

    def test_non_string_data_for_textarea_returns_422(self):
        _create_attribute("textarea_fmt_1", "pim_catalog_textarea")
        res = _create_product("p-textareafmt-1", {"textarea_fmt_1": _value(True)})
        assert res.status_code == 422

    def test_string_data_for_text_succeeds(self):
        _create_attribute("text_fmt_2", "pim_catalog_text")
        res = _create_product("p-textfmt-2", {"text_fmt_2": _value("hello")})
        assert res.status_code == 201

    def test_patch_non_string_data_for_text_returns_422(self):
        _create_attribute("text_fmt_3", "pim_catalog_text")
        client.post("/api/rest/v1/products", json={"identifier": "p-textfmt-patch"})
        res = _patch_product("p-textfmt-patch", {"text_fmt_3": _value({"not": "a string"})})
        assert res.status_code == 422


class TestMediaFileFormatRestriction:
    def test_non_string_data_for_file_returns_422(self):
        _create_attribute("file_fmt_1", "pim_catalog_file")
        res = _create_product("p-filefmt-1", {"file_fmt_1": _value(123)})
        assert res.status_code == 422

    def test_non_string_data_for_image_returns_422(self):
        _create_attribute("img_fmt_1", "pim_catalog_image")
        res = _create_product("p-imgfmt-1", {"img_fmt_1": _value(["list"])})
        assert res.status_code == 422

    def test_string_data_for_file_succeeds(self):
        _create_attribute("file_fmt_2", "pim_catalog_file")
        res = _create_product("p-filefmt-2", {"file_fmt_2": _value("a/b/c/myfile.pdf")})
        assert res.status_code == 201

    def test_patch_non_string_data_for_image_returns_422(self):
        _create_attribute("img_fmt_2", "pim_catalog_image")
        client.post("/api/rest/v1/products", json={"identifier": "p-imgfmt-patch"})
        res = _patch_product("p-imgfmt-patch", {"img_fmt_2": _value(0)})
        assert res.status_code == 422


class TestDateFormatRestriction:
    def test_non_string_data_for_date_returns_422(self):
        _create_attribute("date_fmt_1", "pim_catalog_date")
        res = _create_product("p-datefmt-1", {"date_fmt_1": _value(20210101)})
        assert res.status_code == 422

    def test_dict_data_for_date_returns_422(self):
        _create_attribute("date_fmt_2", "pim_catalog_date")
        res = _create_product("p-datefmt-2", {"date_fmt_2": _value({"year": 2021})})
        assert res.status_code == 422

    def test_string_data_for_date_succeeds(self):
        _create_attribute("date_fmt_3", "pim_catalog_date")
        res = _create_product("p-datefmt-3", {"date_fmt_3": _value("2021-04-29T08:58:00.101Z")})
        assert res.status_code == 201

    def test_patch_non_string_data_for_date_returns_422(self):
        _create_attribute("date_fmt_4", "pim_catalog_date")
        client.post("/api/rest/v1/products", json={"identifier": "p-datefmt-patch"})
        res = _patch_product("p-datefmt-patch", {"date_fmt_4": _value(False)})
        assert res.status_code == 422


class TestSimpleSelectFormatRestriction:
    def test_non_string_data_for_simpleselect_returns_422(self):
        _create_attribute("ss_fmt_1", "pim_catalog_simpleselect")
        res = _create_product("p-ssfmt-1", {"ss_fmt_1": _value(["blue"])})
        assert res.status_code == 422

    def test_string_data_for_simpleselect_succeeds(self):
        _create_attribute("ss_fmt_2", "pim_catalog_simpleselect")
        res = _create_product("p-ssfmt-2", {"ss_fmt_2": _value("blue")})
        assert res.status_code == 201

    def test_non_string_data_for_ref_data_simpleselect_returns_422(self):
        _create_attribute("rds_fmt_1", "pim_catalog_reference_data_simpleselect")
        res = _create_product("p-rdsfmt-1", {"rds_fmt_1": _value(99)})
        assert res.status_code == 422

    def test_non_string_data_for_ref_entity_returns_422(self):
        _create_attribute("re_fmt_1", "akeneo_reference_entity")
        res = _create_product("p-refent-1", {"re_fmt_1": _value({"code": "x"})})
        assert res.status_code == 422

    def test_patch_non_string_data_for_simpleselect_returns_422(self):
        _create_attribute("ss_fmt_3", "pim_catalog_simpleselect")
        client.post("/api/rest/v1/products", json={"identifier": "p-ssfmt-patch"})
        res = _patch_product("p-ssfmt-patch", {"ss_fmt_3": _value(True)})
        assert res.status_code == 422


class TestMultiSelectFormatRestriction:
    def test_non_list_data_for_multiselect_returns_422(self):
        _create_attribute("ms_fmt_1", "pim_catalog_multiselect")
        res = _create_product("p-msfmt-1", {"ms_fmt_1": _value("leather")})
        assert res.status_code == 422

    def test_list_with_non_strings_for_multiselect_returns_422(self):
        _create_attribute("ms_fmt_2", "pim_catalog_multiselect")
        res = _create_product("p-msfmt-2", {"ms_fmt_2": _value(["leather", 42])})
        assert res.status_code == 422

    def test_list_of_strings_for_multiselect_succeeds(self):
        _create_attribute("ms_fmt_3", "pim_catalog_multiselect")
        res = _create_product("p-msfmt-3", {"ms_fmt_3": _value(["leather", "cotton"])})
        assert res.status_code == 201

    def test_non_list_data_for_ref_data_multiselect_returns_422(self):
        _create_attribute("rdm_fmt_1", "pim_catalog_reference_data_multiselect")
        res = _create_product("p-rdmfmt-1", {"rdm_fmt_1": _value("single_code")})
        assert res.status_code == 422

    def test_non_list_data_for_ref_entity_collection_returns_422(self):
        _create_attribute("rec_fmt_1", "akeneo_reference_entity_collection")
        res = _create_product("p-recfmt-1", {"rec_fmt_1": _value("single")})
        assert res.status_code == 422

    def test_non_list_data_for_asset_collection_returns_422(self):
        _create_attribute("ac_fmt_1", "pim_catalog_asset_collection")
        res = _create_product("p-acfmt-1", {"ac_fmt_1": _value("asset_code")})
        assert res.status_code == 422

    def test_list_of_strings_for_asset_collection_succeeds(self):
        _create_attribute("ac_fmt_2", "pim_catalog_asset_collection")
        res = _create_product("p-acfmt-2", {"ac_fmt_2": _value(["asset_a", "asset_b"])})
        assert res.status_code == 201

    def test_patch_non_list_for_multiselect_returns_422(self):
        _create_attribute("ms_fmt_4", "pim_catalog_multiselect")
        client.post("/api/rest/v1/products", json={"identifier": "p-msfmt-patch"})
        res = _patch_product("p-msfmt-patch", {"ms_fmt_4": _value("not_a_list")})
        assert res.status_code == 422


class TestMetricFormatRestriction:
    def test_non_object_data_for_metric_returns_422(self):
        _create_attribute("metric_fmt_1", "pim_catalog_metric")
        res = _create_product("p-metfmt-1", {"metric_fmt_1": _value("800 GRAM")})
        assert res.status_code == 422

    def test_list_data_for_metric_returns_422(self):
        _create_attribute("metric_fmt_2", "pim_catalog_metric")
        res = _create_product("p-metfmt-2", {"metric_fmt_2": _value([800, "GRAM"])})
        assert res.status_code == 422

    def test_object_missing_unit_returns_422(self):
        _create_attribute("metric_fmt_3", "pim_catalog_metric")
        res = _create_product("p-metfmt-3", {"metric_fmt_3": _value({"amount": "800.0"})})
        assert res.status_code == 422

    def test_object_missing_amount_returns_422(self):
        _create_attribute("metric_fmt_4", "pim_catalog_metric")
        res = _create_product("p-metfmt-4", {"metric_fmt_4": _value({"unit": "GRAM"})})
        assert res.status_code == 422

    def test_valid_metric_object_succeeds(self):
        _create_attribute("metric_fmt_5", "pim_catalog_metric")
        res = _create_product("p-metfmt-5", {"metric_fmt_5": _value({"amount": "800.0", "unit": "GRAM"})})
        assert res.status_code == 201

    def test_valid_metric_with_integer_amount_succeeds(self):
        _create_attribute("metric_fmt_6", "pim_catalog_metric")
        res = _create_product("p-metfmt-6", {"metric_fmt_6": _value({"amount": 10, "unit": "KILOWATT"})})
        assert res.status_code == 201

    def test_patch_non_object_metric_returns_422(self):
        _create_attribute("metric_fmt_7", "pim_catalog_metric")
        client.post("/api/rest/v1/products", json={"identifier": "p-metfmt-patch"})
        res = _patch_product("p-metfmt-patch", {"metric_fmt_7": _value(42)})
        assert res.status_code == 422


class TestPriceFormatRestriction:
    def test_non_list_data_for_price_returns_422(self):
        _create_attribute("price_fmt_1", "pim_catalog_price")
        res = _create_product("p-pricefmt-1", {"price_fmt_1": _value({"amount": 200, "currency": "USD"})})
        assert res.status_code == 422

    def test_list_with_non_object_for_price_returns_422(self):
        _create_attribute("price_fmt_2", "pim_catalog_price")
        res = _create_product("p-pricefmt-2", {"price_fmt_2": _value([200])})
        assert res.status_code == 422

    def test_price_object_missing_currency_returns_422(self):
        _create_attribute("price_fmt_3", "pim_catalog_price")
        res = _create_product("p-pricefmt-3", {"price_fmt_3": _value([{"amount": 200}])})
        assert res.status_code == 422

    def test_price_object_missing_amount_returns_422(self):
        _create_attribute("price_fmt_4", "pim_catalog_price")
        res = _create_product("p-pricefmt-4", {"price_fmt_4": _value([{"currency": "USD"}])})
        assert res.status_code == 422

    def test_valid_price_list_succeeds(self):
        _create_attribute("price_fmt_5", "pim_catalog_price")
        res = _create_product("p-pricefmt-5", {"price_fmt_5": _value([{"amount": 200, "currency": "USD"}])})
        assert res.status_code == 201

    def test_valid_price_string_amount_succeeds(self):
        _create_attribute("price_fmt_6", "pim_catalog_price")
        res = _create_product("p-pricefmt-6", {"price_fmt_6": _value([{"amount": "25.50", "currency": "EUR"}])})
        assert res.status_code == 201

    def test_patch_non_list_price_returns_422(self):
        _create_attribute("price_fmt_7", "pim_catalog_price")
        client.post("/api/rest/v1/products", json={"identifier": "p-pricefmt-patch"})
        res = _patch_product("p-pricefmt-patch", {"price_fmt_7": _value("25.50 EUR")})
        assert res.status_code == 422


class TestBooleanFormatRestriction:
    def test_string_data_for_boolean_returns_422(self):
        _create_attribute("bool_fmt_1", "pim_catalog_boolean")
        res = _create_product("p-boolfmt-1", {"bool_fmt_1": _value("true")})
        assert res.status_code == 422

    def test_integer_data_for_boolean_returns_422(self):
        _create_attribute("bool_fmt_2", "pim_catalog_boolean")
        res = _create_product("p-boolfmt-2", {"bool_fmt_2": _value(1)})
        assert res.status_code == 422

    def test_true_boolean_succeeds(self):
        _create_attribute("bool_fmt_3", "pim_catalog_boolean")
        res = _create_product("p-boolfmt-3", {"bool_fmt_3": _value(True)})
        assert res.status_code == 201

    def test_false_boolean_succeeds(self):
        _create_attribute("bool_fmt_4", "pim_catalog_boolean")
        res = _create_product("p-boolfmt-4", {"bool_fmt_4": _value(False)})
        assert res.status_code == 201

    def test_patch_string_for_boolean_returns_422(self):
        _create_attribute("bool_fmt_5", "pim_catalog_boolean")
        client.post("/api/rest/v1/products", json={"identifier": "p-boolfmt-patch"})
        res = _patch_product("p-boolfmt-patch", {"bool_fmt_5": _value("false")})
        assert res.status_code == 422


class TestTableFormatRestriction:
    def test_non_list_data_for_table_returns_422(self):
        _create_attribute("table_fmt_1", "pim_catalog_table")
        res = _create_product("p-tablefmt-1", {"table_fmt_1": _value({"key": "value"})})
        assert res.status_code == 422

    def test_list_with_non_object_row_returns_422(self):
        _create_attribute("table_fmt_2", "pim_catalog_table")
        res = _create_product("p-tablefmt-2", {"table_fmt_2": _value([{"col": "val"}, "not_an_object"])})
        assert res.status_code == 422

    def test_valid_table_list_of_objects_succeeds(self):
        _create_attribute("table_fmt_3", "pim_catalog_table")
        res = _create_product(
            "p-tablefmt-3",
            {"table_fmt_3": _value([{"composition": "wheat", "percentage": "28.5"}, {"composition": "vegetables"}])},
        )
        assert res.status_code == 201

    def test_patch_non_list_for_table_returns_422(self):
        _create_attribute("table_fmt_4", "pim_catalog_table")
        client.post("/api/rest/v1/products", json={"identifier": "p-tablefmt-patch"})
        res = _patch_product("p-tablefmt-patch", {"table_fmt_4": _value("not a table")})
        assert res.status_code == 422


class TestProductLinkFormatRestriction:
    def test_non_object_data_for_product_link_returns_422(self):
        _create_attribute("pl_fmt_1", "pim_catalog_product_link")
        res = _create_product("p-plfmt-1", {"pl_fmt_1": _value("fc24e6c3-933c-4a93-8a81-e5c703d134d5")})
        assert res.status_code == 422

    def test_invalid_type_field_returns_422(self):
        _create_attribute("pl_fmt_2", "pim_catalog_product_link")
        res = _create_product("p-plfmt-2", {"pl_fmt_2": _value({"type": "category", "id": "some_code"})})
        assert res.status_code == 422

    def test_missing_type_field_returns_422(self):
        _create_attribute("pl_fmt_3", "pim_catalog_product_link")
        res = _create_product("p-plfmt-3", {"pl_fmt_3": _value({"id": "fc24e6c3-933c-4a93-8a81-e5c703d134d5"})})
        assert res.status_code == 422

    def test_product_link_missing_id_and_identifier_returns_422(self):
        _create_attribute("pl_fmt_4", "pim_catalog_product_link")
        res = _create_product("p-plfmt-4", {"pl_fmt_4": _value({"type": "product"})})
        assert res.status_code == 422

    def test_product_model_link_missing_id_returns_422(self):
        _create_attribute("pl_fmt_5", "pim_catalog_product_link")
        res = _create_product("p-plfmt-5", {"pl_fmt_5": _value({"type": "product_model"})})
        assert res.status_code == 422

    def test_valid_product_link_with_uuid_succeeds(self):
        _create_attribute("pl_fmt_6", "pim_catalog_product_link")
        res = _create_product(
            "p-plfmt-6",
            {"pl_fmt_6": _value({"type": "product", "id": "fc24e6c3-933c-4a93-8a81-e5c703d134d5"})},
        )
        assert res.status_code == 201

    def test_valid_product_link_with_identifier_succeeds(self):
        _create_attribute("pl_fmt_7", "pim_catalog_product_link")
        res = _create_product(
            "p-plfmt-7",
            {"pl_fmt_7": _value({"type": "product", "identifier": "bl1850b"})},
        )
        assert res.status_code == 201

    def test_valid_product_model_link_succeeds(self):
        _create_attribute("pl_fmt_8", "pim_catalog_product_link")
        res = _create_product(
            "p-plfmt-8",
            {"pl_fmt_8": _value({"type": "product_model", "id": "my_super_battery"})},
        )
        assert res.status_code == 201

    def test_patch_non_object_product_link_returns_422(self):
        _create_attribute("pl_fmt_9", "pim_catalog_product_link")
        client.post("/api/rest/v1/products", json={"identifier": "p-plfmt-patch"})
        res = _patch_product("p-plfmt-patch", {"pl_fmt_9": _value(["product", "uuid"])})
        assert res.status_code == 422
