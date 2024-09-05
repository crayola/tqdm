"""
Module version for monitoring CLI pipes (`... | python -m tqdm | ...`).
"""
import logging
import re
import sys
from ast import literal_eval as numeric
from textwrap import indent

from .std import TqdmKeyError, TqdmTypeError, tqdm
from .version import __version__

__all__ = ["main"]
log = logging.getLogger(__name__)


def cast(val, typ):
    """
    Converts a given value into a specified type, handling various types including
    string, boolean, integer, and floating-point numbers. It supports type casting
    for 'chr' type and handles multiple possible types with 'or' operator.

    Args:
        val (Union[bool, str, int, float, bytes]): Expected to be an input value
            that needs to be cast into a specified data type.
        typ (str | bool): A string representing the data type to which the given
            value should be casted, possibly containing multiple types separated
            by " or ".

    Returns:
        Union[None,bool,int,float,str,bytes]: Casted or converted from a given
        input value and expected data type. It handles various types like bool,
        chr, int, float, str, etc., by attempting to directly convert the input
        into the specified type.

    """
    log.debug((val, typ))
    if " or " in typ:
        for t in typ.split(" or "):
            try:
                return cast(val, t)
            except TqdmTypeError:
                pass
        raise TqdmTypeError(f"{val} : {typ}")

    # sys.stderr.write('\ndebug | `val:type`: `' + val + ':' + typ + '`.\n')
    if typ == 'bool':
        if (val == 'True') or (val == ''):
            return True
        if val == 'False':
            return False
        raise TqdmTypeError(val + ' : ' + typ)
    if typ == 'chr':
        if len(val) == 1:
            return val.encode()
        if re.match(r"^\\\w+$", val):
            return eval(f'"{val}"').encode()
        raise TqdmTypeError(f"{val} : {typ}")
    if typ == 'str':
        return val
    if typ == 'int':
        try:
            return int(val)
        except ValueError as exc:
            raise TqdmTypeError(f"{val} : {typ}") from exc
    if typ == 'float':
        try:
            return float(val)
        except ValueError as exc:
            raise TqdmTypeError(f"{val} : {typ}") from exc
    raise TqdmTypeError(f"{val} : {typ}")


def posix_pipe(fin, fout, delim=b'\\n', buf_size=256,
               callback=lambda float: None, callback_len=True):
    """
    Reads data from a file input stream and writes it to a file output stream,
    optionally buffering at a specified delimiter. It  provides progress callbacks
    for tracking data transfer.

    Args:
        fin (io.IOBase): Read from to transfer data through the pipe.
        fout (io.IOBase): Intended to be an output file object. It should have a
            write method, represented by `fp_write`, which can be used for writing
            data to it.
        delim (bytes | str): 32 bit by default, it represents the delimiter used
            to split data when reading from the input file. It can be an empty
            bytes object or string.
        buf_size (int): 256 by default. It specifies the maximum number of bytes
            that can be read from the input file at one time.
        callback (Callable[[float], None]): Initialized with a default value lambda
            function that takes one argument, always returning None. It is expected
            to be called at specific points during the pipe's execution.
        callback_len (bool): True by default, indicating whether the callback
            should be called with the length of each segment (True) or with the
            segments themselves (False).

    """
    fp_write = fout.write

    if not delim:
        while True:
            tmp = fin.read(buf_size)

            # flush at EOF
            if not tmp:
                getattr(fout, 'flush', lambda: None)()
                return

            fp_write(tmp)
            callback(len(tmp))
        # return

    buf = b''
    len_delim = len(delim)
    # n = 0
    while True:
        tmp = fin.read(buf_size)

        # flush at EOF
        if not tmp:
            if buf:
                fp_write(buf)
                if callback_len:
                    # n += 1 + buf.count(delim)
                    callback(1 + buf.count(delim))
                else:
                    for i in buf.split(delim):
                        callback(i)
            getattr(fout, 'flush', lambda: None)()
            return  # n

        while True:
            i = tmp.find(delim)
            if i < 0:
                buf += tmp
                break
            fp_write(buf + tmp[:i + len(delim)])
            # n += 1
            callback(1 if callback_len else (buf + tmp[:i]))
            buf = b''
            tmp = tmp[i + len_delim:]


# ((opt, type), ... )
RE_OPTS = re.compile(r'\n {4}(\S+)\s{2,}:\s*([^,]+)')
# better split method assuming no positional args
RE_SHLEX = re.compile(r'\s*(?<!\S)--?([^\s=]+)(\s+|=|$)')

# TODO: add custom support for some of the following?
UNSUPPORTED_OPTS = ('iterable', 'gui', 'out', 'file')

# The 8 leading spaces are required for consistency
CLI_EXTRA_DOC = r"""
    Extra CLI Options
    -----------------
    name  : type, optional
        TODO: find out why this is needed.
    delim  : chr, optional
        Delimiting character [default: '\n']. Use '\0' for null.
        N.B.: on Windows systems, Python converts '\n' to '\r\n'.
    buf_size  : int, optional
        String buffer size in bytes [default: 256]
        used when `delim` is specified.
    bytes  : bool, optional
        If true, will count bytes, ignore `delim`, and default
        `unit_scale` to True, `unit_divisor` to 1024, and `unit` to 'B'.
    tee  : bool, optional
        If true, passes `stdin` to both `stderr` and `stdout`.
    update  : bool, optional
        If true, will treat input as newly elapsed iterations,
        i.e. numbers to pass to `update()`. Note that this is slow
        (~2e5 it/s) since every input must be decoded as a number.
    update_to  : bool, optional
        If true, will treat input as total elapsed iterations,
        i.e. numbers to assign to `self.n`. Note that this is slow
        (~2e5 it/s) since every input must be decoded as a number.
    null  : bool, optional
        If true, will discard input (no stdout).
    manpath  : str, optional
        Directory in which to install tqdm man pages.
    comppath  : str, optional
        Directory in which to place tqdm completion.
    log  : str, optional
        CRITICAL|FATAL|ERROR|WARN(ING)|[default: 'INFO']|DEBUG|NOTSET.
"""


def main(fp=sys.stderr, argv=None):
    """
    Implements a command-line interface for the `tqdm` library, allowing users to
    customize and control progress bars for tasks such as file reading or writing,
    while also providing options for output formatting and verbosity.

    Args:
        fp (Union[file-like object, str, int]): Used to specify where progress bar
            output should be written. It defaults to `sys.stderr`.
        argv (Sequence[str]): Used to pass command line arguments to the script.
            If not provided, it defaults to `sys.argv[1:]`. It is later processed
            and split using regular expressions.

    """
    if argv is None:
        argv = sys.argv[1:]
    try:
        log_idx = argv.index('--log')
    except ValueError:
        for i in argv:
            if i.startswith('--log='):
                logLevel = i[len('--log='):]
                break
        else:
            logLevel = 'INFO'
    else:
        # argv.pop(log_idx)
        # logLevel = argv.pop(log_idx)
        logLevel = argv[log_idx + 1]
    logging.basicConfig(level=getattr(logging, logLevel),
                        format="%(levelname)s:%(module)s:%(lineno)d:%(message)s")

    # py<3.13 doesn't dedent docstrings
    d = (tqdm.__doc__ if sys.version_info < (3, 13)
         else indent(tqdm.__doc__, "    ")) + CLI_EXTRA_DOC

    opt_types = dict(RE_OPTS.findall(d))
    # opt_types['delim'] = 'chr'

    for o in UNSUPPORTED_OPTS:
        opt_types.pop(o)

    log.debug(sorted(opt_types.items()))

    # d = RE_OPTS.sub(r'  --\1=<\1>  : \2', d)
    split = RE_OPTS.split(d)
    opt_types_desc = zip(split[1::3], split[2::3], split[3::3])
    d = ''.join(('\n  --{0}  : {2}{3}' if otd[1] == 'bool' else
                 '\n  --{0}=<{1}>  : {2}{3}').format(
                     otd[0].replace('_', '-'), otd[0], *otd[1:])
                for otd in opt_types_desc if otd[0] not in UNSUPPORTED_OPTS)

    help_short = "Usage:\n  tqdm [--help | options]\n"
    d = help_short + """
Options:
  -h, --help     Print this help and exit.
  -v, --version  Print version and exit.
""" + d.strip('\n') + '\n'

    # opts = docopt(d, version=__version__)
    if any(v in argv for v in ('-v', '--version')):
        sys.stdout.write(__version__ + '\n')
        sys.exit(0)
    elif any(v in argv for v in ('-h', '--help')):
        sys.stdout.write(d + '\n')
        sys.exit(0)
    elif argv and argv[0][:2] != '--':
        sys.stderr.write(f"Error:Unknown argument:{argv[0]}\n{help_short}")

    argv = RE_SHLEX.split(' '.join(["tqdm"] + argv))
    opts = dict(zip(argv[1::3], argv[3::3]))

    log.debug(opts)
    opts.pop('log', True)

    tqdm_args = {'file': fp}
    try:
        for (o, v) in opts.items():
            o = o.replace('-', '_')
            try:
                tqdm_args[o] = cast(v, opt_types[o])
            except KeyError as e:
                raise TqdmKeyError(str(e))
        log.debug('args:' + str(tqdm_args))

        delim_per_char = tqdm_args.pop('bytes', False)
        update = tqdm_args.pop('update', False)
        update_to = tqdm_args.pop('update_to', False)
        if sum((delim_per_char, update, update_to)) > 1:
            raise TqdmKeyError("Can only have one of --bytes --update --update_to")
    except Exception:
        fp.write("\nError:\n" + help_short)
        stdin, stdout_write = sys.stdin, sys.stdout.write
        for i in stdin:
            stdout_write(i)
        raise
    else:
        buf_size = tqdm_args.pop('buf_size', 256)
        delim = tqdm_args.pop('delim', b'\\n')
        tee = tqdm_args.pop('tee', False)
        manpath = tqdm_args.pop('manpath', None)
        comppath = tqdm_args.pop('comppath', None)
        if tqdm_args.pop('null', False):
            class stdout(object):
                """
                Defines a static method `write` that does nothing when called,
                effectively overriding the standard behavior of writing to the
                console. This can be used for testing or debugging purposes where
                output is suppressed.

                """
                @staticmethod
                def write(_):
                    """
                    Serves as an interface to allow output operations on the
                    standard output stream, but it does not implement any actual
                    writing functionality and simply passes through its arguments
                    without effecting any changes or actions.

                    Args:
                        _ (Any): Intended to be ignored or not used within the
                            function, allowing for optional parameters in the
                            calling function. It is commonly used as a "throwaway"
                            variable.

                    """
                    pass
        else:
            stdout = sys.stdout
            stdout = getattr(stdout, 'buffer', stdout)
        stdin = getattr(sys.stdin, 'buffer', sys.stdin)
        if manpath or comppath:
            from importlib import resources
            from os import path
            from shutil import copyfile

            def cp(name, dst):
                """
                Copies a file specified by `name` from either a `files` attribute
                or a path within the `resources.path` to a destination location
                `dst`, and logs a message indicating the copied file's new path.

                Args:
                    name (str): Used to specify the name of a file within the
                        'tqdm' resources that needs to be copied. It is likely a
                        filename, not a path.
                    dst (str): Used to specify the destination file path where the
                        file will be copied. It appears to represent the full path
                        of the target file.

                """
                if hasattr(resources, 'files'):
                    copyfile(str(resources.files('tqdm') / name), dst)
                else:  # py<3.9
                    with resources.path('tqdm', name) as src:
                        copyfile(str(src), dst)
                log.info("written:%s", dst)
            if manpath is not None:
                cp('tqdm.1', path.join(manpath, 'tqdm.1'))
            if comppath is not None:
                cp('completion.sh', path.join(comppath, 'tqdm_completion.sh'))
            sys.exit(0)
        if tee:
            stdout_write = stdout.write
            fp_write = getattr(fp, 'buffer', fp).write

                                   """
                                   Modifies the behavior of the standard output
                                   by combining it with a progress bar from `tqdm`.
                                   It writes input to the file pointer (`fp`) while
                                   displaying a progress bar for each write operation.

                                   """
            class stdout(object):  # pylint: disable=function-redefined
                @staticmethod
                def write(x):
                    """
                    Writes data to file or console, depending on the write mode
                    specified by tqdm's external_write_mode. If set to console,
                    it calls `fp_write` and `stdout_write`; otherwise, it only
                    calls `tqdm.external_write_mode`.

                    Args:
                        x (Union[bytes, str]): Expected to be data that needs to
                            be written either to the file or to stdout.

                    """
                    with tqdm.external_write_mode(file=fp):
                        fp_write(x)
                    stdout_write(x)
        if delim_per_char:
            tqdm_args.setdefault('unit', 'B')
            tqdm_args.setdefault('unit_scale', True)
            tqdm_args.setdefault('unit_divisor', 1024)
            log.debug(tqdm_args)
            with tqdm(**tqdm_args) as t:
                posix_pipe(stdin, stdout, '', buf_size, t.update)
        elif delim == b'\\n':
            log.debug(tqdm_args)
            write = stdout.write
            if update or update_to:
                with tqdm(**tqdm_args) as t:
                    if update:
                        def callback(i):
                            t.update(numeric(i.decode()))
                    else:  # update_to
                        def callback(i):
                            t.update(numeric(i.decode()) - t.n)
                    for i in stdin:
                        write(i)
                        callback(i)
            else:
                for i in tqdm(stdin, **tqdm_args):
                    write(i)
        else:
            log.debug(tqdm_args)
            with tqdm(**tqdm_args) as t:
                callback_len = False
                if update:
                    def callback(i):
                        t.update(numeric(i.decode()))
                elif update_to:
                    def callback(i):
                        t.update(numeric(i.decode()) - t.n)
                else:
                    callback = t.update
                    callback_len = True
                posix_pipe(stdin, stdout, delim, buf_size, callback, callback_len)
