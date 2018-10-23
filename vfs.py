#!/usr/bin/python3
import base64
import errno
import io
import os
import sys

import PIL.Image
import magic

# FIXME: Put this in a config file somehow
_CONFIG_MEDIA_PATH = '/srv/media/Video'

# FIXME: Use a smaller (presumably therefore more efficient) database file.
#        Perhaps with just video/* & image/* filetypes in it?
magic_db = magic.open(sum((
    magic.SYMLINK,  # Follow symlinks
    magic.MIME_TYPE,  # Just report the mimetype, don't make it human-readable.
    magic.PRESERVE_ATIME,  # Preserve the file access time, since I'm only using this when listing the directories
    # Literally just [i for i in dir(magic) if i.startswith('NO_CHECK')]
    # I expect that by disabling all these checks it should be quicker & more efficient.
    magic.NO_CHECK_APPTYPE,
    magic.NO_CHECK_BUILTIN,
    magic.NO_CHECK_CDF,
    magic.NO_CHECK_COMPRESS,
    magic.NO_CHECK_ELF,
    magic.NO_CHECK_ENCODING,
    magic.NO_CHECK_SOFT,
    magic.NO_CHECK_TAR,
    # I need to actually check for text files for the .info files
    # magic.NO_CHECK_TEXT
    magic.NO_CHECK_TOKENS,
)))
magic_db.load()  # FIXME: Does this close cleanly?


class vfs_Object():
    """Base class for other vfs objects to inherit"""
    # I want to cache all of these values, but only after they've been queried at least once
    _uri = None
    _sortkey = None
    _mimetype = ''
    preview = None

    def __repr__(self):
        # The '!r' runs repr on the object, which I'm using in this case just so that the pathname gets quoted well
        return '<{modname}.{classname} {pathname!r}>'.format(
            modname=self.__module__, classname=self.__class__.__name__, pathname=self._fullpath)

    def __init__(self, path, sortkey=''):
        if self.__class__.__name__ == 'vfs_Object':
            raise NotImplementedError("vfs_Object is not supposed to be used directly")

        if path.startswith(_CONFIG_MEDIA_PATH):
            self._relpath = path[len(_CONFIG_MEDIA_PATH):].lstrip(os.path.sep)
            self._fullpath = path
        else:
            self._relpath = path
            self._fullpath = os.path.join(os.path.abspath(_CONFIG_MEDIA_PATH), path)

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
            self._mimetype = magic_db.file(self._fullpath)
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
    def __init__(self, *args, **kwargs):
        self.preview = self
        super().__init__(*args, **kwargs)

    def get_thumbnail(self, size=(280, 180)):  # FIXME: Default size inherited from UPMC, get a better size
        assert isinstance(size, tuple)
        assert len(size) == 2
        image_buffer = io.BytesIO()
        im = PIL.Image.open(self._fullpath)
        im.thumbnail(size=size)
        im.save(image_buffer, format='png')  # FIXME: Is PNG reasonable? Not using JPEG because I want alpha channel support
        image_buffer.seek(0)
        b64_data = base64.b64encode(image_buffer.read())
        image_buffer.close()
        return b64_data.decode('ascii')


class Folder(vfs_Object):
    """Folder class, iterate across this to get File/Video/Image objects for each directory entry"""
    _isfile = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # FIXME: This criteria stolen from UPMC.
        #        Reasonable while still using the UPMC storage backend, but should get tidied up later,
        #        probably by just going "No! The folder preview must be a png..." etc.
        for ext in ['.jpg', '.png', '.jpeg', '.gif']:
            for filename in ['folder' + ext, '.folder' + ext, 'folder' + ext.upper(), '.folder' + ext.upper()]:
                try: self.preview = Image(os.path.join(self._fullpath, filename))  # noqa: E701
                except FileNotFoundError: continue  # noqa: E701
                else: break  # noqa: E701

    def __iter__(self):
        self._index = 0
        self._objects = {}
        # Since dicts are not sorted, I keep a separately sorted list of the dict keys
        # FIXME: This name is misleading as it's not actually sorted until after the loop
        self._sorted_list = []
        for entry in os.scandir(self._fullpath):
            # If it's not hidden, and it is a file or directory (therefore not a broken symlink)
            # FIXME: Add a "show_hidden" flag somehow?
            if not entry.name.startswith('.') and (entry.is_file() or entry.is_dir()):
                sortkey = _get_sortkey(entry)
                if sortkey not in self._objects:
                    self._sorted_list.append(sortkey)
                    self._objects[sortkey] = []
                self._objects[sortkey].append(entry)
        self._sorted_list.sort()
        return self

    def __next__(self):
        if self._index >= len(self._objects):
            raise StopIteration
        else:
            sortkey = self._sorted_list[self._index]
            self._index += 1
            if len(self._objects[sortkey]) == 1:
                entry, = self._objects[sortkey]
                if entry.is_dir():
                    return Folder(entry.path, sortkey=sortkey)
                else:
                    print("WARNING: No metadata for", entry.path, file=sys.stderr)
                    return self._get_file(entry.path, sortkey=sortkey)
            else:
                # Multiple associated files to deal with.
                video = None
                image = None
                for entry in self._objects[sortkey]:
                    assert not entry.is_dir(), "Directories shouldn't have extensions"
                    f = self._get_file(entry.path, sortkey=sortkey)
                    if isinstance(f, Video):
                        video = f
                    elif isinstance(f, Image):
                        image = f
#                    elif isinstance(f, Subtitles):
#                        subtitles = f
                    else:
                        # Unrecognised file, just going to ignore this one.
                        pass
                if video is None and image is None:
                    # No associated video or image file found, so skip this entry and move on.
                    return self.__next__()
                elif video is None:
                    # There's an image but no associated video
                    return image
                elif image is None:
                    # There's a videobut no associated image
                    # No other part of the code really does anything with this yet, but I'll return it as is anyway
                    return video
                else:
                    # There's both an image and a video
                    video.preview = image
                    return video

            raise Exception("Reaching this point should be impossible")

    def _get_file(self, path, sortkey):
        # FIXME: Make the magic DB smaller & more efficient, this is the slowest part of all
        # FIXME: Make the magic DB recognise SRT files.
        mimetype = magic_db.file(path)
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
            sortkey = _get_sortkey(name=self.name, is_file=True)
            return self._get_file(fullpath, sortkey=sortkey)


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
        name = name.rsplit(os.path.extsep, 1)[0]

    # False sorts before True, so directories will come first
    sortkey = is_file, name
    return sortkey
