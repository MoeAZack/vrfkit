"""Shared test scaffolding. Imports nothing from tools/; importing it puts tools/ on sys.path."""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1]
REPO = TOOLS.parent
sys.path.insert(0, str(TOOLS))


class TempDirTestCase(unittest.TestCase):
    def tmp(self) -> Path:
        """A fresh directory removed when the test ends."""
        return Path(self.enterContext(tempfile.TemporaryDirectory()))


def read_parquet(path):
    """Materialize one fixture file and close its input before returning."""
    import pyarrow.parquet as pq

    with pq.ParquetFile(path, pre_buffer=False) as source:
        return source.read()


@contextlib.contextmanager
def retained_parquet_readers():
    """Keep real readers alive until ownership assertions have run."""
    import pyarrow.parquet as pq

    readers, real_reader = [], pq.ParquetFile
    with contextlib.ExitStack() as cleanup:
        def retain(*args, **kwargs):
            reader = real_reader(*args, **kwargs)
            cleanup.callback(reader.close)
            readers.append(reader)
            return reader

        with mock.patch.object(pq, "ParquetFile", side_effect=retain):
            yield readers


def run_cli(main, *argv, prog=None, merged=False):
    """Run a tool's main and return (code, stdout, stderr); SystemExit propagates.

    With `prog`, argv is patched into sys.argv and main() takes no arguments; otherwise
    main(list(argv)). merged=True writes both streams, in order, to stdout.
    """
    args, out, err = [str(a) for a in argv], io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out if merged else err):
        if prog is None:
            code = main(args)
        else:
            with mock.patch.object(sys, "argv", [prog, *args]):
                code = main()
    return code, out.getvalue(), err.getvalue()
