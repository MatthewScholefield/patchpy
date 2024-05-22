from abc import abstractmethod, ABC
from argparse import ArgumentParser
from dataclasses import dataclass, field
from enum import Enum
from http.client import HTTPResponse
from itertools import chain
from pathlib import Path
from typing import List, Optional, Self, Union
import re
import os
import urllib.request

from more_itertools import peekable

RE_HUNK_START = re.compile(r'^@@ -(\d+)(,(\d+))? \+(\d+)(,(\d+))? @@')


class PatchPyError(RuntimeError):
    pass


class ParsedObj(ABC):
    @classmethod
    def parse(cls, s: str) -> Self:
        return cls._parse(peekable(s.splitlines(keepends=True)))

    @abstractmethod
    def validate(self):
        pass

    @classmethod
    @abstractmethod
    def _parse(cls, lines: 'peekable[str]') -> Self:
        pass

    @abstractmethod
    def to_string(self) -> str:
        pass


@dataclass
class Hunk(ParsedObj):
    """A section of a file that has been changed"""

    original_start: int  # The starting line number in the original file.
    original_length: (
        int  # The number of lines in the original file that the hunk applies to.
    )
    new_start: int  # The starting line number in the new file.
    new_length: int  # The number of lines in the new file that the hunk applies to.
    original_lines: List[str] = field(
        default_factory=list
    )  # The lines from the original file (including context lines).
    new_lines: List[str] = field(
        default_factory=list
    )  # The lines from the new file (including context lines).

    def validate(self):
        if self.original_length != len(self.original_lines):
            raise PatchPyError(
                f'Number of original lines does not match original length metadata: {len(self.original_lines)} != {self.original_length}'
            )
        if self.new_length != len(self.new_lines):
            raise PatchPyError(
                f'Number of new lines does not match new length metadata: {len(self.new_lines)} != {self.new_length}'
            )
        if len(self.original_lines) == len(self.new_lines) and all(
            a == b for a, b in zip(self.original_lines, self.new_lines)
        ):
            raise PatchPyError('Hunk is empty')

    def fix_counts(self):
        self.original_length = len(self.original_lines)
        self.new_length = len(self.new_lines)

    @classmethod
    def _parse(cls, lines: 'peekable[str]') -> 'Hunk':
        match = RE_HUNK_START.match(header_line := next(lines))
        if not match:
            raise PatchPyError(f'Invalid hunk header: {header_line}')
        original_start = int(match.group(1))
        original_length = int(match.group(3) or 1)
        new_start = int(match.group(4))
        new_length = int(match.group(6) or 1)
        original_lines = []
        new_lines = []
        while lines:
            line = lines.peek()
            if line.startswith((' ', '-', '+')):
                if not line.startswith('-'):
                    new_lines.append(line[1:])
                if not line.startswith('+'):
                    original_lines.append(line[1:])
                next(lines)
            else:
                break
        return cls(
            original_start=original_start,
            original_length=original_length,
            new_start=new_start,
            new_length=new_length,
            original_lines=original_lines,
            new_lines=new_lines,
        )

    def to_string(self) -> str:
        shared_lines_start = 0
        for original_line, new_line in zip(self.original_lines, self.new_lines):
            if original_line != new_line:
                break
            shared_lines_start += 1
        shared_lines_end = 0
        for original_line, new_line in zip(
            reversed(self.original_lines), reversed(self.new_lines)
        ):
            if original_line != new_line:
                break
            shared_lines_end += 1
        formatted_lines = (
            [' ' + line for line in self.original_lines[:shared_lines_start]]
            + [
                '-' + line
                for line in self.original_lines[
                    shared_lines_start : len(self.original_lines) - shared_lines_end
                ]
            ]
            + [
                '+' + line
                for line in self.new_lines[
                    shared_lines_start : len(self.new_lines) - shared_lines_end
                ]
            ]
            + [
                ' ' + line
                for line in self.original_lines[
                    len(self.original_lines) - shared_lines_end :
                ]
            ]
        )
        return (
            f'@@ -{self.original_start},{self.original_length} +{self.new_start},{self.new_length} @@\n'
            + ''.join(formatted_lines)
        )


class ModificationKind(Enum):
    REGULAR = 1
    GIT = 2  # Git-style modifications (a/ and b/ prefixes on paths)


@dataclass
class FileModification(ParsedObj):
    kind: ModificationKind
    header: List[
        str
    ]  # Any lines in the header of the modification (git uses to reference objects etc.)
    source: Optional[str]  # String path to the source of the diff
    target: Optional[str]  # String path to the target of the diff
    hunks: List[Hunk]  # List of the changed lines in the file

    def validate(self):
        for hunk in self.hunks:
            hunk.validate()
        if not self.source and not self.target:
            raise PatchPyError('Both source and target are /dev/null')
        if self.source:
            self._validate_path(self.source)
        if self.target:
            self._validate_path(self.target)

    def _validate_path(self, path: str):
        if Path(path).is_absolute():
            raise PatchPyError(f'Path is absolute: {path}')
        folder_depth = 0
        for part in Path(path).parts:
            if part == '..':
                folder_depth -= 1
            elif part:
                folder_depth += 1
            if folder_depth < 0:
                raise PatchPyError(f'Path escapes root directory: {path}')

    def fix_counts(self):
        for hunk in self.hunks:
            hunk.fix_counts()

    def apply(
        self, strip: int = 0, root: Optional[Union[str, bytes, os.PathLike]] = None
    ):
        root_path = Path(root) if root else Path.cwd()
        source_path = (
            root_path / Path(*Path(self.source).parts[strip:]) if self.source else None
        )
        target_path = (
            root_path / Path(*Path(self.target).parts[strip:]) if self.target else None
        )
        if source_path and not source_path.exists():
            raise PatchPyError(f'Source file {source_path} does not exist')
        if not self.source and not self.target:
            return
        if self.source and not self.target:
            os.unlink(source_path)
            return
        if not self.source and self.target:
            for hunk in self.hunks:
                if not hunk.original_lines == []:
                    raise PatchPyError('Source file is /dev/null but hunk is not empty')
            target_path.write_text(
                ''.join(chain.from_iterable(hunk.new_lines for hunk in self.hunks))
            )
            return
        with source_path.open() as f:
            source_lines = f.readlines()

        self.hunks.sort(key=lambda h: h.original_start)

        target_line_chunks = []
        current_line = 0  # To keep track of the current line in source_lines

        for hunk in self.hunks:
            if current_line > hunk.original_start - 1:
                raise PatchPyError('Hunks overlap or are out of order')

            hunk_start = hunk.original_start - 1
            hunk_end = hunk_start + hunk.original_length
            target_line_chunks.append(source_lines[current_line:hunk_start])

            original_hunk_source = ''.join(hunk.original_lines)
            actual_hunk_source = ''.join(source_lines[hunk_start:hunk_end])
            if original_hunk_source != actual_hunk_source:
                raise PatchPyError(
                    f'Hunk does not match the source file!\n{original_hunk_source}\n---\n{actual_hunk_source}'
                )

            target_line_chunks.append(hunk.new_lines)
            current_line = hunk_end
        target_line_chunks.append(source_lines[current_line:])
        target_path.write_text(''.join(chain.from_iterable(target_line_chunks)))

    def reversed(self) -> 'FileModification':
        return FileModification(
            kind=self.kind,
            header=self.header,
            source=self.target,
            target=self.source,
            hunks=[
                Hunk(
                    original_start=hunk.new_start,
                    original_length=hunk.new_length,
                    new_start=hunk.original_start,
                    new_length=hunk.original_length,
                    original_lines=hunk.new_lines,
                    new_lines=hunk.original_lines,
                )
                for hunk in self.hunks
            ],
        )

    @classmethod
    def _parse(cls, lines: 'peekable[str]') -> 'FileModification':
        header = []
        while lines:
            line = lines.peek()
            if line.startswith('--- '):
                break
            header.append(next(lines))
        source = next(lines).removeprefix('--- ')
        if not lines or not lines.peek().startswith('+++ '):
            raise PatchPyError(f'Invalid patch header: {line}')
        target = next(lines).removeprefix('+++ ')
        source = cls._decode_path(source)
        target = cls._decode_path(target)
        kind = ModificationKind.REGULAR
        if header and header[0].startswith('diff --git'):
            source = source.removeprefix('a/') if source else None
            target = target.removeprefix('b/') if target else None
            kind = ModificationKind.GIT
        hunks = []
        while lines and lines.peek().startswith('@@ '):
            hunks.append(Hunk._parse(lines))
        return cls(kind=kind, header=header, source=source, target=target, hunks=hunks)

    @staticmethod
    def _decode_path(path_suffix: str) -> Optional[str]:
        content = path_suffix.removesuffix('\n').split('\t', 1)[0]
        if content.startswith('"') and content.endswith('"'):
            content = content[1:-1]

            def repl(m):
                s = m.group(1)
                if s.isdigit():
                    return bytes([int(s, 8)])
                if s[0] in 'xu':
                    return bytes([int(s[1:], 16)])
                if s in 'abtnvfr':
                    return {
                        'a': b'\a',
                        'b': b'\b',
                        't': b'\t',
                        'n': b'\n',
                        'v': b'\v',
                        'f': b'\f',
                        'r': b'\r',
                    }[s]
                return s

            content = re.sub(
                rb'\\([0-3]?[0-7]{2}|u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|.)',
                repl,
                content.encode(),
            ).decode()
        if content == '/dev/null':
            return None
        return content

    def to_string(self) -> str:
        header = ''.join(self.header)
        is_git = self.kind == ModificationKind.GIT
        source = ('a/' * is_git + self.source) if self.source else '/dev/null'
        target = ('b/' * is_git + self.target) if self.target else '/dev/null'
        return (
            header
            + f'--- {source}\n+++ {target}\n'
            + ''.join(hunk.to_string() for hunk in self.hunks)
        )


@dataclass
class DiffFile(ParsedObj):
    modifications: List[FileModification]

    def diffstat(self) -> str:
        stats = []
        for mod in self.modifications:
            stats.append(f'{mod.source} -> {mod.target}')
            for hunk in mod.hunks:
                stats.append(
                    f" {hunk.original_length} {'+' if hunk.new_length else '-'}"
                )
        return '\n'.join(stats)

    def apply(
        self, strip: int = 0, root: Optional[Union[str, bytes, os.PathLike]] = None
    ) -> bool:
        self.validate()
        for mod in self.modifications:
            mod.apply(strip, root)

    def reversed(self) -> 'DiffFile':
        return DiffFile([mod.reversed() for mod in self.modifications])

    def fix_counts(self):
        for mod in self.modifications:
            mod.fix_counts()

    def validate(self):
        for mod in self.modifications:
            mod.validate()

    @classmethod
    def from_path(cls, path: Union[str, bytes, os.PathLike]) -> 'DiffFile':
        return cls.from_string(Path(path).read_text())

    @classmethod
    def from_string(cls, s: str) -> 'DiffFile':
        return cls.parse(s)

    @classmethod
    def _parse(cls, lines: 'peekable[str]') -> 'DiffFile':
        items = []
        while lines:
            items.append(FileModification._parse(lines))
        return cls(items)

    def to_string(self) -> str:
        return ''.join(mod.to_string() for mod in self.modifications)


def main():
    parser = ArgumentParser(description='Tool to interact with patch files.')
    sp = parser.add_subparsers(dest='command', required=True, help='Command to run')
    p = sp.add_parser('apply', help='Apply a patch')
    p.add_argument(
        'diff_file', type=str, nargs='+', help='Path or URL of the diff file'
    )
    p.add_argument(
        '-d', '--directory', type=str, help='Root directory for applying the patch'
    )
    p.add_argument(
        '-p',
        '--strip',
        type=int,
        default=0,
        help='Remove N leading path components from file paths',
    )
    p.add_argument(
        '--revert', action='store_true', help='Apply the patch in reverse (unpatch)'
    )
    p = sp.add_parser('transform', help='Transform a patch')
    p.add_argument('diff_file', type=str, help='Path or URL of the diff file')
    p.add_argument(
        '-o', '--output', type=str, help='Path to write the transformed patch'
    )
    p.add_argument('-r', '--reverse', action='store_true', help='Reverse the patch')
    p.add_argument(
        '-f',
        '--fix-counts',
        action='store_true',
        help='Fix the line counts in the patch',
    )
    p = sp.add_parser('diffstat', help='Show diffstat of a patch')
    p.add_argument(
        'diff_file', type=str, nargs='*', help='Path or URL of the diff file'
    )
    args = parser.parse_args()

    if args.command == 'apply':
        diff_files = [_diff_file_from_arg(arg) for arg in args.diff_file]

        for diff_file in diff_files:
            diff_file.validate()

        try:
            if args.revert:
                diff_file.reversed().apply(args.strip, root=args.directory)
            else:
                diff_file.apply(args.strip, root=args.directory)
        except PatchPyError as e:
            print('Error:', e)
            exit(1)
    elif args.command == 'transform':
        diff_file = _diff_file_from_arg(args.diff_file)
        if args.reverse:
            diff_file = diff_file.reversed()
        if args.fix_counts:
            diff_file.fix_counts()
        if args.output:
            Path(args.output).write_text(diff_file.to_string())
        else:
            print(diff_file.to_string())
    elif args.command == 'diffstat':
        diff_files = [_diff_file_from_arg(arg) for arg in args.diff_file]
        for diff_file in diff_files:
            print(diff_file.diffstat())
    else:
        assert False


def _diff_file_from_arg(arg: str) -> DiffFile:
    if arg.startswith('http://') or arg.startswith('https://'):
        with urllib.request.urlopen(arg) as response:
            response: HTTPResponse
            return DiffFile.from_string(response.read().decode('utf-8'))
    else:
        return DiffFile.from_path(arg)


if __name__ == '__main__':
    main()
