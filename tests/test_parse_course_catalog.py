"""Unit tests for scripts/parse_course_catalog.py.

Uses a small synthetic source doc reproducing the two real formatting quirks
found in DUSD's actual Google-Docs export: inconsistent heading spacing
("| Engineering |" vs "|  English |") and a giant reference-style base64
image definition dumped at the end of the file regardless of where the image
is actually used.
"""
from pathlib import Path

from scripts.parse_course_catalog import _clean, parse

SAMPLE_DOC = """# Front matter

Graduation requires 230 credits total.

| Engineering |
| :---: |

**PLTW Introduction to Engineering Design \\(IED\\)**
Grade Level:  9-l2
Essential Skills: None

An intro engineering course.

|  Mathematics |
| :---: |

**Algebra I**
Grade Level:  9-l2

Covers linear equations.

[image1]: <data:image/png;base64,not-a-real-image-but-imagine-its-huge>
"""


SAMPLE_HEADINGS = ["Engineering", "Mathematics"]


def test_parse_splits_front_matter_and_departments(tmp_path):
    source = tmp_path / "catalog.md"
    source.write_text(SAMPLE_DOC)

    data = parse(source, headings=SAMPLE_HEADINGS)

    assert "230 credits" in data["overview"]
    assert "Engineering" not in data["overview"]
    assert set(data["departments"].keys()) == {"Engineering", "Mathematics"}
    assert "IED" in data["departments"]["Engineering"]
    assert "Algebra I" in data["departments"]["Mathematics"]
    # Each department's own text stays out of the other's.
    assert "Algebra I" not in data["departments"]["Engineering"]


def test_parse_strips_embedded_image_data_uris(tmp_path):
    """Regression test: a base64 image data: URI dumped at the end of the
    file used to get swept into whichever department happened to be last,
    ballooning a ~20K-char section to ~770K in the real document."""
    source = tmp_path / "catalog.md"
    source.write_text(SAMPLE_DOC)

    data = parse(source, headings=SAMPLE_HEADINGS)

    assert "base64" not in data["departments"]["Mathematics"]
    assert "data:image" not in data["departments"]["Mathematics"]


def test_clean_unescapes_markdown_export_punctuation():
    assert _clean("PLTW \\(IED\\) \\- Design") == "PLTW (IED) - Design"


def test_clean_fixes_l2_ocr_artifact_in_grade_ranges():
    assert _clean("Grade Level: 9-l2") == "Grade Level: 9-12"


def test_clean_does_not_mangle_unrelated_text():
    assert _clean("Room L2 is upstairs") == "Room L2 is upstairs"
