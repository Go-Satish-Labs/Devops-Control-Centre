import csv
import io
import json
from xml.etree import ElementTree as ET

from src.reporting.csv_generator import CSV_COLUMNS, render_csv
from src.reporting.json_generator import render_json
from src.reporting.markdown_generator import render_markdown
from src.reporting.svg_generator import render_svg
from tests.fakes import make_audit, repo_dict

SVG_NS = "{http://www.w3.org/2000/svg}"


def test_svg_is_valid_xml_and_escapes_hostile_names():
    svg = render_svg(make_audit([repo_dict(name='<script>alert(1)</script>&"x"')]))
    ET.fromstring(svg)
    assert "<script" not in svg.lower()
    assert "&lt;script&gt;" in svg


def test_svg_renders_with_no_repositories():
    root = ET.fromstring(render_svg(make_audit([])))
    assert root.find(SVG_NS + "title") is not None


def test_svg_limits_large_repository_lists():
    repos = [repo_dict(name=f"repo-{i:03d}") for i in range(120)]
    svg = render_svg(make_audit(repos), row_limit=40)
    ET.fromstring(svg)
    assert "+ 80 more repositories" in svg


def test_svg_has_no_scripts_or_external_references():
    svg = render_svg(make_audit([repo_dict()])).lower()
    assert "<script" not in svg
    assert "<image" not in svg
    assert "@import" not in svg
    assert "href=" not in svg


def test_json_round_trips():
    audit = make_audit([repo_dict()])
    assert json.loads(render_json(audit))["organization"] == "Go-Satish-Labs"


def test_markdown_escapes_table_breaking_characters():
    md = render_markdown(make_audit([repo_dict(name="a|b")]))
    assert "a\\|b" in md
    assert md.startswith("# Organization health")


def test_csv_has_expected_columns_and_neutralises_formulas():
    text = render_csv(make_audit([repo_dict(name="=HYPERLINK(1)")]))
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == CSV_COLUMNS
    assert rows[1][0].startswith("'=")
    assert len(rows) == 2
