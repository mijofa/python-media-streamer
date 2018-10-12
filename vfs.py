#!/usr/bin/python3
import errno
import os

import magic

# FIXME: Put this in a config file somehow
_CONFIG_MEDIA_PATH = '/srv/media/Video'


class vfs_Object():
    """Base class for other vfs objects to inherit"""
    # I want to cache all of these values, but only after they've been queried at least once
    _uri = None
    _sortkey = None
    _mimetype = ''

    def __repr__(self):
        # The '!r' runs repr on the object, which I'm using in this case just so that the pathname gets quoted well
        return '<{modname}.{classname} {pathname!r}>'.format(
            modname=self.__module__, classname=self.__class__.__name__, pathname=self._fullpath)

    def __init__(self, path, sortkey=''):
        if self.__class__.__name__ == 'vfs_Object':
            raise NotImplementedError("vfs_Object is not supposed to be used directly")

        self._relpath = path

        self._fullpath = os.path.join(os.path.abspath(_CONFIG_MEDIA_PATH), self._relpath)
        if not os.path.exists(self._fullpath):
            raise FileNotFoundError(errno.ENOENT, "No such file or directory", path)
        if self._isfile is not None:
            if self._isfile and not os.path.isfile(self._fullpath):
                raise FileNotFoundError(errno.ENOENT, "Not a file", path)
            elif not self._isfile and not os.path.isdir(self._fullpath):
                raise FileNotFoundError(errno.ENOENT, "Not a directory", path)

        # Need to strip os.path.sep first to stop 'foo/bar/' from returning '', because it ends with a '/'
        self._name = os.path.basename(self._relpath.strip(os.path.sep))

        self._sortkey = sortkey

    ## Read only properties ##

    @property
    def local_uri(self):
        """The local URI for accessing this resource, for use with applications on the server such as ffmpeg"""
        return 'file:{}'.format(self._fullpath)

    @property
    def path(self):
        return self._relpath

    @property
    def name(self):
        return self._name

    @property
    def hidden(self):
        return self._name.startswith('.')

    @property
    def mimetype(self):
        if not self._mimetype:
            self._mimetype = magic.detect_from_filename(self._fullpath).mime_type
        return self._mimetype

    @property
    def sortkey(self):
        if not self._sortkey:
            self._sortkey = _get_sortkey(name=self.name, is_file=self._isfile)
        return self._sortkey


class File(vfs_Object):
    """Generic file class"""
    _isfile = True

    def __init__(self, path, mimetype='', **kwargs):
        super().__init__(path, **kwargs)
        self._mimetype = mimetype


class Video(File):
    pass


class Image(File):
    pass


class Folder(vfs_Object):
    """Folder class, iterate across this to get File/Video/Image objects for each directory entry"""
    _isfile = False

    def __iter__(self):
        self._index = 0
        # If it's neither a file or a directory, it's probably a broken symlink, just ignore it
        # Also ignore hidden files, they don't matter for the iterable
        # FIXME: Add a "show_hidden" flag somehow?
        self._iterable = [(_get_sortkey(e), e) for e in os.scandir(self._fullpath)
                          if not e.name.startswith('.') and (e.is_file() or e.is_dir())]
        self._iterable.sort()
        return self

    def __next__(self):
        if self._index >= len(self._iterable):
            raise StopIteration
        else:
            sortkey, entry = self._iterable[self._index]
            self._index += 1
            if entry.is_file():
                return self._get_file(entry.path, sortkey=sortkey)
            elif entry.is_dir():
                return Folder(entry.path, sortkey=sortkey)

            raise Exception("Reaching this point should be impossible")

    def _get_file(self, path, sortkey):
        # FIXME: Make the magic DB smaller & more efficient, this is the slowest part of all
        # FIXME: Make the magic DB recognise SRT files.
        mimetype = magic.detect_from_filename(path).mime_type
        type_cat = mimetype.partition('/')[0]
        if type_cat == 'video':
            return Video(path, mimetype=mimetype, sortkey=sortkey)
        elif type_cat == 'image':
            return Image(path, mimetype=mimetype, sortkey=sortkey)
        else:
            return File(path, mimetype=mimetype, sortkey=sortkey)

    def __getitem__(self, name: str):
        if type(name) != str:
            raise TypeError("Folder indices must be strings")

        fullpath = os.path.join(self._fullpath, name)

        if not os.path.exists(fullpath):
            raise IndexError("No such file or directory")

        if os.path.isdir(fullpath):
            return Folder(fullpath)
        else:
            return self._get_file(fullpath)


def _get_sortkey(entry=None, name='', is_file=None):
    if entry is None:
        assert name and isinstance(is_file, bool)
    else:
        name = entry.name
        is_file = entry.is_file()
    first_word = name.split(maxsplit=1)[0]
    if first_word.lower() in ('the', 'an', 'a'):
        # Sort "The Truman Show" as "Truman Show, The"
        # Sort "An Easter Carol" as "Easter Carol, An"
        # Sort "A Fish Called Wanda" as "Fish Called Wanda, A"
        name = "{name}, {first}".format(name=name[len(first_word) + 1:], first=first_word)
    # FIXME: Turn roman numerals ("Part II", "Part IV", etc) into digits.
    #        But how can I identify what's a roman numberal and what's just an I in the title?
    # FIXME: Should I even try to do anything about Ocean's Eleven/Twelve/Thirteen/Eight?
    #        For that particular series there's no right answer (8 before 11 is wrong, but so is E before T)
    #        Does anything else spell out the numbers instead of using digits or roman numerals?

    # FIXME: One thing I did in UPMC was add 1 to the end of everything that had no digits,
    #        so as to make "Foo" sort before "Foo 2".
    #        I think this is solvable in the locale, but I don't know how
    # This *might* help with that, needs testing
    if is_file:
        name, ext = name.rsplit(os.path.extsep, 1)
    else:
        ext = ''

    # False sorts before True, so directories will come first
    sortkey = is_file, name, ext
    return sortkey
