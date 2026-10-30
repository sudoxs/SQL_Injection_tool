
import json

import pytest

from SQLI import (
    Obfuscator,
    apply_context_escape,
    escape_html,
    find_placeholders_in_string,
    js_string_escape,
    looks_encoded,
    parse_multi_indices,
    sql_escape,
    to_int_safe,
    xml_escape_str,
)


def test_to_int_safe_accepts_persian_digits():
    assert to_int_safe("۱۲۳", min_val=1, max_val=200) == 123


def test_to_int_safe_rejects_out_of_range():
    with pytest.raises(ValueError):
        to_int_safe("25", min_val=1, max_val=20)


def test_parse_multi_indices():
    assert parse_multi_indices("1,3-5,7", 7) == [1, 3, 4, 5, 7]


def test_parse_all_indices():
    assert parse_multi_indices("all", 3) == [1, 2, 3]


def test_sql_escape():
    assert sql_escape("O'Reilly") == "O''Reilly"


def test_html_escape():
    assert escape_html("<script>") == "&lt;script&gt;"


def test_xml_escape():
    assert xml_escape_str("<a&b>") == "&lt;a&amp;b&gt;"


def test_json_escape_round_trip():
    original = 'hello "world"\nsecond line'
    escaped = json.dumps(original)[1:-1]

    assert json.loads(f'"{escaped}"') == original


def test_javascript_escape():
    escaped = js_string_escape("<tag>")

    assert "\\x3c" in escaped
    assert "\\x3e" in escaped


def test_context_escape():
    assert apply_context_escape("a&b", "html") == "a&amp;b"


def test_looks_encoded():
    assert looks_encoded("id=%20")
    assert not looks_encoded("normal-value")


def test_find_placeholders():
    value = "id={ID}&token={TOKEN}&again={ID}"

    assert find_placeholders_in_string(value) == ["ID", "TOKEN"]


def test_invalid_dbms_falls_back_to_mysql():
    obfuscator = Obfuscator(dbms="InvalidDBMS")

    assert obfuscator.dbms == "MySQL"


def test_url_encoding_layer():
    obfuscator = Obfuscator()

    result = obfuscator._apply_encoding_layers(
        "hello world",
        ["url"]
    )

    assert result == "hello%20world"
