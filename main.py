#!/usr/bin/python3
import errno
import os
import sys
import urllib.parse

import flask
import magic

import ffmpeg

app = flask.Flask("web-emcee")

# NOTE: This temporary directory is not secure because it's predictable,
#       but I'm only intending to use it for transcoding cache, so that's ok.
# FIXME: Clear this cache on startup
TMP_DIR = os.path.join(os.environ.get('XDG_RUNTIME_DIR', os.environ.get('TMPDIR', '/tmp/')), app.name)

media_path = sys.argv[1] if len(sys.argv) > 1 else os.path.curdir
media_path += '/' if not media_path.endswith('/') else ''


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
    ## I need to actually check for text files
    # magic.NO_CHECK_TEXT
    magic.NO_CHECK_TOKENS,
)))


def get_mediauri(filename):
    filepath = os.path.join(os.path.abspath(media_path), filename)
    if not os.path.exists(filepath) or os.path.isdir(filepath):
        # Technically this is invalid for "isdir", but good enough.
        raise FileNotFoundError(errno.ENOENT, "No such media file", filename)
    fileuri = 'file:' + filepath
    del filename
    del filepath

    return fileuri


@app.route('/')
def index():
    return "Indexing isn't supported yet"


def _sort_key(entry):
    # Takes a posix.DirEntry object and makes it more intelligently sortable
    if entry.is_file() and '.' in entry.name and not entry.name.startswith('.'):
        name, ext = entry.name.rsplit('.', maxsplit=1)
    else:
        name = entry.name
        ext = ''
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
    # False comes before True, so this will put directories first
    return entry.is_file(), name, ext


# NOTE: The trailing '/' is important!
#       Without that Flask will remove any trailing slash, breaking the relative links
@app.route('/browse/', defaults={'dirpath': ''})
@app.route('/browse/<path:dirpath>/')
def browse(dirpath):
    dirpath = os.path.join(os.path.abspath(media_path), dirpath)
    if not os.path.exists(dirpath) or not os.path.isdir(dirpath):
        # Technically this is invalid for "isdir", but good enough.
        raise FileNotFoundError(errno.ENOENT, "No such directory", dirpath)

    entries = list(os.scandir(dirpath))
    # False sorts before True
    # So this makes directories first, then sorts by name
    # FIXME: Give each entry object a sort_key variable,
    #        because it needs to be used for more than just the actual sorting.
    #    eg: Give each letter a heading in the listing.
    entries.sort(key=_sort_key)
    ret_html = "<html><head></head><body>"
    for e in entries:
        if not e.name.startswith('.'):  # Hide hidden files & directories
            if not e.is_file():
                # Note I use e.name here instead of the path because I can just use it as a relative path.
                ret_html += "<a href={path}/>{name}/</a><br>".format(path=urllib.parse.quote(e.name), name=e.name)
            else:
                # FIXME: just chdir into the root on start, then it need never be in a variable again
                path = e.path[len(media_path):]  # Remove the media_path root directory from the path
                ftype = magic_db.file(e.path)  # FIXME: This still isn't fast enough!
                if ftype.startswith('video/'):
                    ret_html += "<a href=/watch/{path}>{name}</a><br>".format(path=urllib.parse.quote(path), name=e.name)
                else:
                    ret_html += "<a href=/raw_media/{path}>{name}</a><br>".format(path=urllib.parse.quote(path), name=e.name)
    ret_html += "</body>"
    resp = flask.make_response(ret_html)
    resp.mimetype = 'text/html'
    return resp


@app.route('/watch/<path:filename>')
def watch(filename):
    try:
        get_mediauri(filename)
    except FileNotFoundError as e:
        return ' '.join((e.strerror, e.filename)), 404

    return flask.send_from_directory('static', 'player.html', mimetype='text/html')


@app.route('/watch/<path:filename>/get_captions.vtt')
def get_captions(filename):
    fileuri = get_mediauri(filename)

    resp = flask.make_response(ffmpeg.get_captions(fileuri, flask.request.args.get('index')))
    # Must return vtt regardless of input type
    resp.mimetype = 'text/vtt'
    return resp


@app.route('/watch/<path:filename>/get_caption_tracks.json')
def get_caption_tracks(filename):
    fileuri = get_mediauri(filename)

    resp = flask.make_response(ffmpeg.get_caption_tracks(fileuri))
    resp.mimetype = "application/json"
    return resp


@app.route('/watch/<path:filename>/hls-manifest.m3u8')
def manifest(filename):
    fileuri = get_mediauri(filename)
    output_dir = os.path.join(TMP_DIR, os.path.basename(fileuri))  # FIXME: foo/S01E02 and bar/S01E02 will conflict

    resp = flask.make_response(ffmpeg.get_manifest(output_dir, fileuri))
    resp.cache_control.no_cache = True
    return resp


@app.route('/watch/<path:filename>/hls-segment-<int:index>.ts')
def hls_segment(filename, index):
    fileuri = get_mediauri(filename)
    output_dir = os.path.join(TMP_DIR, os.path.basename(fileuri))  # FIXME: foo/S01E02 and bar/S01E02 will conflict

    return ffmpeg.get_segment(output_dir, index)


@app.route('/watch/<path:filename>/duration')
def duration(filename):
    fileuri = get_mediauri(filename)

    # Flask can't handle a float here, so must cast it to a str.
    return str(ffmpeg.get_duration(fileuri))


@app.route('/raw_media/<path:filename>')
def raw_media(filename):
    return flask.send_from_directory(media_path, filename)


# Chromecast requires CORS headers for all media resources, I don't yet understand CORS headers.
# This is just enough to make Chromecast work, haphazardly stolen from https://gist.github.com/blixt/54d0a8bf9f64ce2ec6b8
#
# FIXME: Make sense of CORS headers, and implement them properly.
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response
app.after_request(add_cors_headers)  # noqa: E305


# Chromecast refuses to use the DNS server specified by DHCP without messing with the firewall rules to block Google's DNS.
# I could do that workaround, but I'd rather this be able to work without network specific config such as that,
# so instead I tried to push that DNS resolution onto the browser, but Javascript can't do DNS like that.
#
# Last resort, this HTTP path will respond with the server's IP address that the client is coming in via,
# so if listening on multiple interfaces/IPs it will respond with only the one the client is currently using.
# FIXME: Won't currently work via a reverse proxy.
@app.route('/get_ip')
def get_ip():
    """Tell the client what the server's external IP address."""
    assert len(flask.request.access_route) == 1
    return flask.request.access_route[0]


if __name__ == "__main__":
    if not os.path.isdir(TMP_DIR):
        os.mkdir(TMP_DIR)
    magic_db.load()  # FIXME: Use a smaller (more specifically relevant) database file rather than the default
    app.run(debug=True, host='0.0.0.0', threaded=True)
    magic_db.close()  # FIXME: Will this ever actually run?
