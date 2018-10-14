#!/usr/bin/python3
import errno
import json
import os
import sys

import flask
import magic

import ffmpeg

import vfs

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
    return "Front page not designed yet"


@app.route('/browser/ls.json', defaults={'dirpath': ''})
@app.route('/browser/<path:dirpath>/ls.json')
def listdir(dirpath):
    entries = [{
        'is_file': isinstance(e, vfs.File),
        'mimetype': e.mimetype,
        'name': e.name,
        'path': e.path,
        'sortkey': e.sortkey,
        'preview': e.preview.get_thumbnail() if e.preview else None,
    } for e in vfs.Folder(dirpath)]

    json_str = json.dumps(entries)

    return json_str


# NOTE: The trailing '/' is important!
#       Without that Flask will remove any trailing slash, breaking the relative links
@app.route('/browser/', defaults={'dirpath': ''})
@app.route('/browser/<path:dirpath>/')
def browser(dirpath):
    return flask.send_from_directory('static', 'browser.html', mimetype='text/html')


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
