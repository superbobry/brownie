# coding: utf-8
"""
    brownie.terminal
    ~~~~~~~~~~~~~~~~

    Utilities for handling simple output on a terminal.


    .. versionadded:: 0.6

    :copyright: 2010-2011 by Daniel Neuhäuser
    :license: BSD, see LICENSE.rst for details
"""
from __future__ import with_statement
import re
import os
import sys
import codecs
import struct
try:
    # all available on unix platforms
    import fcntl
    import termios
except ImportError: # pragma: no cover
    fcntl = None
    termios = None
from itertools import izip, imap
from contextlib import contextmanager

from brownie.text import transliterate
from brownie.datastructures import namedtuple
from brownie.terminal.progress import ProgressBar


_ansi_sequence = '\033[%sm'


ATTRIBUTES = dict((key, _ansi_sequence % value) for key, value in [
    ('reset','00'),
    ('bold',  '01'),
    ('faint', '02'),
    ('standout', '03'),
    ('underline', '04'),
    ('blink', '05')
])
TEXT_COLOURS = {'reset': _ansi_sequence % '39'}
BACKGROUND_COLOURS = {'reset': _ansi_sequence % '49'}
_colour_names = [
    'black',
    'red',
    'green',
    'yellow',
    'blue',
    'purple',
    'teal',
    'white'
]
for i, name in enumerate(_colour_names):
    TEXT_COLOURS[name] = _ansi_sequence % str(i + 30)
    BACKGROUND_COLOURS[name] = _ansi_sequence % (i + 40)


Dimensions = namedtuple('Dimensions', ['height', 'width'], doc="""
    A namedtuple representing the dimensions of a terminal.

    :param height:
        The height of the terminal.

    :param width:
        The width of the terminal.
""")



class TerminalWriter(object):
    """
    This is a helper for dealing with output to a terminal.

    :param stream:
        The stream to which the output is written, per default `sys.stdout`.

    :param fallback_encoding:
        The encoding used if `stream` doesn't provide one.

    :param prefix:
        A prefix used when an entire line is written.

    :param indent:
        String used for indentation.

    :param autoescape:
        Defines if everything written is escaped (unless explicitly turned
        off), see :func:`escape` for more information.

    :param ignore_options:
        Defines if options should be ignored or not, per default options are
        ignored if the `stream` is not a tty.

    After each call resulting in visible characters to be written to the
    `stream` the stream is flushed, certain methods allow to override this
    behaviour.
    """
    #: Specifies the default terminal width.
    default_width = 80

    def __init__(self, stream=sys.stdout, fallback_encoding='ascii', prefix=u'',
                 indent=' ' * 4, autoescape=True, ignore_options=None):
        #: The stream to which the output is written.
        self.stream = stream
        #: Encoding used if :attr:`stream` doesn't provide one.
        self.fallback_encoding = fallback_encoding
        #: The prefix used by :meth:`writeline`.
        self.prefix = prefix
        #: The string used for indentation.
        self.indent_string = indent
        #: ``True`` if escaping should be done automatically.
        self.autoescape = autoescape

        is_a_tty = getattr(stream, 'isatty', lambda: False)()

        if ignore_options is None and is_a_tty:
            self.ignore_options = False
        elif ignore_options is None:
            self.ignore_options = True
        else:
            self.ignore_options = ignore_options

        if is_a_tty and termios and hasattr(stream, 'fileno'):
            self.control_characters = [
                c for c in termios.tcgetattr(stream.fileno())[-1]
                if isinstance(c, basestring)
            ]
        else:
            # just to be on the safe side...
            self.control_characters = map(chr, range(32) + [127])

        self.ansi_re = re.compile('[%s]' % ''.join(self.control_characters))
        self.indentation_level = 0

    @property
    def encoding(self):
        """
        The encoding provided by the stream or :attr:`fallback_encoding`.
        """
        return getattr(self.stream, 'encoding', self.fallback_encoding)

    def encode(self, string):
        try:
            return string.encode(self.encoding)
        except UnicodeError:
            return transliterate(string, length='one').encode('ascii')

    def escape(self, string):
        """
        Escapes all control characters in the given `string`.

        This is useful if you are dealing with 'untrusted' strings you want to
        write to a file, stdout or stderr which may be viewed using tools such
        as `cat` which execute ANSI escape sequences.

        .. seealso::

           http://www.ush.it/team/ush/hack_httpd_escape/adv.txt
        """
        return self.ansi_re.sub(
            lambda m: m.group().encode('unicode-escape'),
            string
        )

    def get_dimensions(self):
        """
        Returns a :class:`Dimensions` object.

        May raise :exc:`NotImplementedError` depending on the stream or
        platform.
        """
        try:
            fileno = self.stream.fileno()
        except AttributeError:
            pass
        else:
            return Dimensions(*struct.unpack('hhhh', fcntl.ioctl(
                fileno, termios.TIOCGWINSZ, '\000' * 8)
            )[:2])
        raise NotImplementedError(
            'not implemented for the given stream or platform'
        )

    def get_width(self, default=None):
        """
        Returns the width of the terminal.

        This falls back to the `COLUMNS` environment variable and if that fails
        to :attr:`default_width` unless `default` is not None, in which case
        `default` would be used.

        Therefore the returned value might not not be at all correct.
        """
        default = self.default_width if default is None else default
        try:
            _, width = self.get_dimensions()
        except NotImplementedError:
            width = int(os.environ.get('COLUMNS', default))
        return width

    def get_usable_width(self, default_width=None):
        """
        Returns the width of the terminal remaining once the prefix and
        indentation has been written.

        :param default_width:
            The width which is assumed per default for the terminal, see
            :meth:`get_width` for more information.

        .. warning::
           Tabs are considered to have a length of 1. This problem may be
           solved in the future until then it is recommended to avoid tabs.
        """
        return self.get_width(default_width) - (
            len(self.prefix) + len(self.indent_string * self.indentation_level)
        )

    def indent(self):
        """
        Indent the following lines with the given :attr:`indent`.
        """
        self.indentation_level += 1

    def dedent(self):
        """
        Dedent the following lines.
        """
        self.indentation_level -= 1

    @contextmanager
    def options(self, text_colour=None, background_colour=None, bold=None,
                faint=None, standout=None, underline=None, blink=None,
                indentation=False, escape=None):
        """
        A contextmanager which allows you to set certain options for the
        following writes.

        :param text_colour:
            The desired text colour.

        :param background_colour:
            The desired background colour.

        :param bold:
            If present the text is displayed bold.

        :param faint:
            If present the text is displayed faint.

        :param standout:
            If present the text stands out.

        :param underline:
            If present the text is underlined.

        :param blink:
            If present the text blinks.

        :param indentation:
            Adds a level of indentation if ``True``.

        :param escape:
            Overrides the escaping behaviour for this block.

        .. note::
           The underlying terminal may support only certain options, especially
           the attributes (`bold`, `faint`, `standout` and `blink`) are not
           necessarily available.

        The following colours are available, the exact colour varies between
        terminals and their configuration.

        .. ansi-block::
           :string_escape:

           Colors
           ======
           \x1b[30mblack\x1b[0m  \x1b[33myellow\x1b[0m \x1b[36mteal\x1b[0m
           \x1b[31mred\x1b[0m    \x1b[34mblue\x1b[0m   \x1b[37mwhite\x1b[0m
           \x1b[32mgreen\x1b[0m  \x1b[35mpurple\x1b[0m
        """
        attributes = [
            name for name, using in [
                ('bold', bold), ('faint', faint), ('standout', standout),
                ('underline', underline), ('blink', blink)
            ]
            if using
        ]
        if not self.ignore_options:
            if text_colour:
                self.stream.write(TEXT_COLOURS[text_colour])
            if background_colour:
                self.stream.write(BACKGROUND_COLOURS[background_colour])
            for attribute in attributes:
                if attribute:
                    self.stream.write(ATTRIBUTES[attribute])
        if indentation:
            self.indent()
        if escape is not None:
            previous_setting = self.autoescape
            self.autoescape = escape
        try:
            yield self
        finally:
            if not self.ignore_options:
                if text_colour:
                    self.stream.write(TEXT_COLOURS['reset'])
                if background_colour:
                    self.stream.write(BACKGROUND_COLOURS['reset'])
                if any(attributes):
                    self.stream.write(ATTRIBUTES['reset'])
            if indentation:
                self.dedent()
            if escape is not None:
                self.autoescape = previous_setting

    def begin_line(self):
        """
        Writes the prefix and indentation to the stream.
        """
        self.write(
            self.prefix + (self.indent_string * self.indentation_level),
            escape=False,
            flush=False
        )

    @contextmanager
    def line(self):
        """
        A contextmanager which can be used instead of :meth:`writeline`.

        This is useful if you want to write a line with multiple different
        options.
        """
        self.begin_line()
        try:
            yield
        finally:
            self.newline()

    def newline(self):
        """
        Writes a newline to the :attr:`stream`.
        """
        self.write('\n', escape=False, flush=False)

    def should_escape(self, escape):
        """
        Returns :attr:`autoescape` if `escape` is None otherwise `escape`.
        """
        return self.autoescape if escape is None else escape

    def write(self, string, escape=None, flush=True, **options):
        """
        Writes the `given` string to the :attr:`stream`.

        :param escape:
            Overrides :attr:`autoescape` if given.

        :param options:
            Options for this operation, see :meth:`options`.

        :param flush:
            If ``True`` flushes the stream.
        """
        with self.options(**options):
            escaped = self.escape(string) if self.should_escape(escape) else string
            encoded = self.encode(escaped)
            self.stream.write(encoded)
            if flush:
                self.stream.flush()

    def writeline(self, line, escape=None, flush=True, **options):
        """
        Writes the given `line` to the :attr:`stream` respecting indentation.

        :param escape:
            Overrides :attr:`autoescape` if given.

        :param options:
            Options for this operation, see :meth:`options`.

        :param flush:
            If ``True`` flushes the stream.
        """
        with self.options(**options):
            self.begin_line()
            self.write(line, escape=self.should_escape(escape), flush=False)
            self.newline()
            if flush:
                self.stream.flush()

    def writelines(self, lines, escape=None, flush=True, **options):
        """
        Writes each line in the given iterable to the :attr:`stream` respecting
        indentation.

        :param escape:
            Overrides :attr:`autoescape` if given.

        :param options:
            Options for this operation, see :meth:`options`.

        :param flush:
            If ``True`` flushes the stream.
        """
        with self.options(**options):
            for line in lines:
                self.writeline(line, escape=escape, flush=False)
            if flush:
                self.stream.flush()

    def hr(self, character=u'-'):
        """
        Writes a horizontal ruler with the width of the terminal to the
        :attr:`stream`.

        :param character:
            Specifies the character used for the ruler.
        """
        self.writeline(character * self.get_width())

    def table(self, content, head=None, padding=1):
        """
        Writes a table using a list of rows (`content`) and an optional `head`.

        :param padding:
            Specifies the padding used for each cell to the left and right.

        ::

            >>> import sys
            >>> from brownie.terminal import TerminalWriter
            >>> writer = TerminalWriter.from_bytestream(sys.stdout)
            >>> writer.table([
            ...     [u'foo', u'bar'],
            ...     [u'spam', u'eggs']
            ... ])
            foo  | bar
            spam | eggs
            <BLANKLINE>
            >>> writer.table(
            ...     [
            ...         [u'foo', u'bar'],
            ...         [u'spam', u'eggs']
            ...     ],
            ...     [u'hello', u'world']
            ... )
            hello | world
            ------+------
            foo   | bar
            spam  | eggs
            <BLANKLINE>
        """
        if not content:
            raise ValueError()
        if head is not None and len(head) != len(content[0]):
            raise ValueError()
        if any(len(content[0]) != len(row) for row in content[1:]):
            raise ValueError()
        all_rows = [head] if head is not None else [] + content
        cell_lengths = [
            max(map(len, column)) for column in izip(*all_rows)
        ]
        def make_line(row):
            return u'|'.join(
                u' ' * padding + cell.ljust(cell_lengths[i]) + u' ' * padding
                for i, cell in enumerate(imap(self.escape, row))
            ).strip()
        result = map(make_line, content)
        if head:
            line = make_line(head)
            self.writeline(line, escape=False)
            self.writeline(
                re.sub(r'[^\|]', '-', line)
                    .replace('|', '+')
                    .ljust(max(map(len, result)), '-'),
                escape=False
            )
        self.writelines(result, flush=False)
        self.newline()
        self.stream.flush()

    def progress(self, description, maxsteps=None, widgets=None):
        """
        Returns a :class:`~brownie.terminal.progress.ProgressBar` object
        which can be used to write the current progress to the stream.

        The progress bar is created from the `description` which is a string
        with the following syntax:

        Widgets -- the parts of the progress bar which are changed with each
        update -- are represented in the form ``$[a-zA-Z]+``.

        Some widgets required that you provide an initial value, this can be
        done by adding ``:string`` where string is either ``[a-zA-Z]+`` or a
        double-quoted string.

        If you want to escape a ``$`` you simply precede it with another ``$``,
        so ``$$foo` will not be treated as a widget and in the progress bar
        ``$foo`` will be shown.

        Quotes (``"``) in strings can be escaped with a backslash (``\``).

        The following widgets are available:

        `hint`
            Shows a string of text that can be given using the `hint` argument
            at any update performed with :meth:`.ProgressBar.init`,
            :meth:`.ProgressBar.next` or :meth:`.ProgressBar.finish`. If the
            argument is not given an empty string is used instead.

        `percentage`
            Shows the progress in percent; this requires `maxsteps` to be set.

        `bar`
            Shows a simple bar which moves which each update not corresponding
            with the progress being made. This is useful if you just want to
            show that something is happening.

        `sizedbar`
            Shows a simple progress bar which is being filled corresponding
            to the percentage of progress. This requires `maxsteps` to be
            set.

        `step`
            Shows the current at maximum number of steps as ``step of steps``,
            this method takes an initial value determining the unit of each
            step e.g. if each step represents a byte and you choose `bytes`
            as a unit a reasonable prefix will be chosen.

            Supported units:

            - `bytes` - Uses a binary prefix.

            This requires `maxsteps` to be set.

        `time`
            Shows the elapsed time in hours, minutes and seconds.

        `speed`
            Shows the speed in bytes (or with a reasonable prefix) per seconds,
            this assumes that each `step` represents a byte.

        If you want to implement your own widget(s) take a look at
        :class:`brownie.terminal.progress.Widget`, you can use them by passing
        them in a dictionary (mapping the name to the widget class) via the
        `widgets` argument. You might also want to take a look at the source
        code of the built-in widgets.

        There are two things you have to look out for:
        :class:`~brownie.terminal.progress.ProgressBar` objects are not
        reusable if you need another object, call this method again. If you
        attempt to write to the :attr:`stream` while using a progress bar the
        behaviour is undefined.

        .. seealso:: :ref:`creating-widgets`
        """
        return ProgressBar.from_string(
            description, self, maxsteps=maxsteps, widgets=None
        )

    def __repr__(self):
        return '%s(%r, %r, %r, %r, %r, %r)' % (
            self.__class__.__name__, self.stream, self.fallback_encoding,
            self.prefix, self.indent_string, self.autoescape,
            self.ignore_options
        )
