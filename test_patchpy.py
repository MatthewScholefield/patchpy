import pytest
from pathlib import Path
import tempfile

from patchpy import Hunk, FileModification, DiffFile, PatchPyError, ModificationKind

# Sample diff for testing
sample_diff = """--- a/sample.txt
+++ b/sample.txt
@@ -1,3 +1,4 @@
 Line 1
 Line 2
 Line 3
+Line 4
"""

# Sample diff with multiple hunks
sample_diff_multi_hunk = """--- a/sample.txt
+++ b/sample.txt
@@ -1,3 +1,4 @@
 Line 1
 Line 2
 Line 3
+Line 4
@@ -5,3 +6,4 @@
 Line 5
 Line 6
 Line 7
+Line 8
"""

# Sample diff with header
sample_diff_with_header = """diff --git a/sample.txt b/sample.txt
index 83db48f..f735c3d 100644
--- a/sample.txt
+++ b/sample.txt
@@ -1,3 +1,4 @@
 Line 1
 Line 2
 Line 3
+Line 4
"""

# Sample diff with folder prefix
sample_diff_with_prefix = """--- foo/sample.txt
+++ bar/sample.txt
@@ -1,3 +1,4 @@
 Line 1
 Line 2
 Line 3
+Line 4
"""


# Sample invalid diff
sample_invalid_diff = """--- a/sample.txt
+++ b/sample.txt
@@ -1,3 +1,4 @@
 Line 1
 Line 2
 Line 3
 Line 4
"""

sample_diff_with_escaping_path = """--- "foo/../../sample.txt
+++ "bar/../../sample.txt
@@ -1,3 +1,4 @@
 Line 1
 Line 2
 Line 3
+Line 4
"""


def test_hunk_parsing():
    hunk = Hunk.parse(''.join(sample_diff.splitlines(keepends=True)[2:]))
    assert hunk.original_start == 1
    assert hunk.original_length == 3
    assert hunk.new_start == 1
    assert hunk.new_length == 4
    assert hunk.original_lines == ['Line 1\n', 'Line 2\n', 'Line 3\n']
    assert hunk.new_lines == ['Line 1\n', 'Line 2\n', 'Line 3\n', 'Line 4\n']


def test_file_modification_parsing():
    mod = FileModification.parse(sample_diff)
    assert mod.source == 'sample.txt'
    assert mod.target == 'sample.txt'
    assert len(mod.hunks) == 1
    hunk = mod.hunks[0]
    assert hunk.original_start == 1
    assert hunk.original_length == 3
    assert hunk.new_start == 1
    assert hunk.new_length == 4


def test_diff_file_parsing():
    diff_file = DiffFile.parse(sample_diff)
    assert len(diff_file.modifications) == 1
    mod = diff_file.modifications[0]
    assert mod.source == 'sample.txt'
    assert mod.target == 'sample.txt'
    assert len(mod.hunks) == 1


def test_diff_file_to_string():
    diff_file = DiffFile.parse(sample_diff)
    assert diff_file.to_string() == sample_diff


def test_diff_file_apply():
    with tempfile.TemporaryDirectory() as tempdir:
        sample_path = Path(tempdir) / 'sample.txt'
        sample_path.write_text('Line 1\nLine 2\nLine 3\n')
        diff_file = DiffFile.from_string(sample_diff)
        diff_file.apply(root=tempdir)
        assert sample_path.read_text() == 'Line 1\nLine 2\nLine 3\nLine 4\n'


def test_diff_file_reversed():
    diff_file = DiffFile.from_string(sample_diff)
    reversed_diff = diff_file.reversed()
    assert (
        reversed_diff.to_string()
        == """--- a/sample.txt
+++ b/sample.txt
@@ -1,4 +1,3 @@
 Line 1
 Line 2
 Line 3
-Line 4
"""
    )


def test_diff_file_diffstat():
    diff_file = DiffFile.from_string(sample_diff)
    assert diff_file.diffstat() == 'sample.txt -> sample.txt\n 3 +'


def test_invalid_diff():
    with pytest.raises(PatchPyError):
        DiffFile.from_string(sample_invalid_diff).validate()


def test_multi_hunk_diff():
    diff_file = DiffFile.from_string(sample_diff_multi_hunk)
    assert len(diff_file.modifications) == 1
    mod = diff_file.modifications[0]
    assert len(mod.hunks) == 2


def test_diff_with_header():
    diff_file = DiffFile.from_string(sample_diff_with_header)
    assert len(diff_file.modifications) == 1
    mod = diff_file.modifications[0]
    assert mod.kind == ModificationKind.GIT
    assert mod.header == [
        'diff --git a/sample.txt b/sample.txt\n',
        'index 83db48f..f735c3d 100644\n',
    ]


def test_fix_counts():
    diff_file = DiffFile.from_string(sample_diff)
    for mod in diff_file.modifications:
        for hunk in mod.hunks:
            hunk.original_lines.pop()
            hunk.fix_counts()
            assert hunk.original_length == len(hunk.original_lines)
            assert hunk.new_length == len(hunk.new_lines)


def test_validate():
    diff_file = DiffFile.from_string(sample_diff)
    for mod in diff_file.modifications:
        for hunk in mod.hunks:
            hunk.original_lines.pop()
            with pytest.raises(PatchPyError):
                hunk.validate()


def test_apply_with_strip():
    with tempfile.TemporaryDirectory() as tempdir:
        sample_path = Path(tempdir) / 'sample.txt'
        sample_path.write_text('Line 1\nLine 2\nLine 3\n')
        diff_file = DiffFile.from_string(sample_diff_with_prefix)
        diff_file.apply(strip=1, root=tempdir)
        assert sample_path.read_text() == 'Line 1\nLine 2\nLine 3\nLine 4\n'


def test_apply_with_revert():
    with tempfile.TemporaryDirectory() as tempdir:
        sample_path = Path(tempdir) / 'sample.txt'
        sample_path.write_text('Line 1\nLine 2\nLine 3\nLine 4\n')
        diff_file = DiffFile.from_string(sample_diff)
        diff_file.reversed().apply(root=tempdir)
        assert sample_path.read_text() == 'Line 1\nLine 2\nLine 3\n'


def test_apply_with_escaping_path():
    with pytest.raises(PatchPyError):
        DiffFile.from_string(sample_diff_with_escaping_path).validate()
