# PatchPy

*A modern Python library for patch file parsing (diff file parsing)*

PatchPy is a Python library for parsing and applying patch files.

```python
patch_file = PatchFile.from_path("example.patch")
patch_file.validate()
reversed_patch = patch_file.reversed()
reversed_patch.apply(root=".")
```

**Features:**

 - Parse unified and context diff formats
 - Apply/revert patches with optional path stripping
 - Fix line counts in hunk headers

## Installation

Install via [PyPI](https://pypi.org/project/patchpy/):

```sh
pip install patchpy
```

## Usage

### Library API

You can use PatchPy programmatically within your Python code. Here is a simple example:

```python
from patchpy import DiffFile

# Load a patch from a file
diff_file = DiffFile.from_path("example.patch")

# Validate the patch (ie. checks line counts in hunk headers)
diff_file.validate()

# Get attributes of the patch
print(diff_file.modifications[0].header)

# Reverse the patch and apply it
reversed_patch = diff_file.reversed()
reversed_patch.apply(root=".")
```

### CLI

The PatchPy CLI provides a simple interface for applying patches. Below is an example of how to use it:

```sh
# Apply a patch file
patchypy apply example.patch

# Apply a patch from a URL
patchypy apply https://example.com/patch.diff

# Display diffstat
patchypy diffstat example.patch

# Apply a patch with stripped leading path components
patchypy apply example.patch -p 1

# Transform a patch
patchypy transform --revert example.patch -o reversed.patch 

# Fix line counts in hunk headers in patch
patchpy transfform --fix-counts example.patch -o fixed.patch
```

## Development

PatchPy uses Rye for dependency management and development workflow. To get started with development, ensure you have [Rye](https://github.com/astral-sh/rye) installed and then clone the repository and set up the environment:

```sh
git clone https://github.com/MatthewScholefield/patchpy.git
cd patchpy
rye sync
rye run pre-commit install

# Run tests
rye test
```

Contributions are welcome! Feel free to open issues or submit pull requests.
