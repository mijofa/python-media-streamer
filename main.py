#!/usr/bin/python3
import sys
import os

import flask

import ffmpeg

app = flask.Flask("web-emcee")

# NOTE: This temporary directory is not secure because it's predictable,
#       but I'm only intending to use it for transcoding cache, so that's ok.
# FIXME: Clear this cache on startup
TMP_DIR = os.path.join(os.environ.get('XDG_RUNTIME_DIR', os.environ.get('TMPDIR', '/tmp/')), app.name)

media_path = sys.argv[1] if len(sys.argv) > 1 else os.path.curdir


def get_mediauri(filename):
    filepath = os.path.join(os.path.abspath(media_path), filename)
    assert os.path.exists(filepath) and not os.path.isdir(filepath)
    fileuri = 'file:' + filepath
    del filename
    del filepath

    return fileuri


@app.route('/')
def index():
    return "Indexing isn't supported yet"


@app.route('/watch/<path:filename>')
def watch(filename):
    return flask.send_from_directory('static', 'player.html', mimetype='text/html')


@app.route('/watch/<path:filename>/subtitles-<string:language>.vtt')
@app.route('/watch/<path:filename>/subtitles.vtt', defaults={'language': 'English'})
def subtitles(filename, language):
    fileuri = get_mediauri(filename)

    resp = flask.make_response(ffmpeg.get_subtitles(fileuri, language))
    resp.mimetype = 'text/vtt'
    return resp


@app.route('/watch/<path:filename>/hls-manifest.m3u8')
def manifest(filename):
    fileuri = get_mediauri(filename)
    output_dir = os.path.join(TMP_DIR, os.path.basename(fileuri))

    resp = flask.make_response(ffmpeg.get_manifest(output_dir, fileuri))
    resp.cache_control.no_cache = True
    return resp


@app.route('/watch/<path:filename>/hls-segment-<int:index>.ts')
def hls_segment(filename, index):
    fileuri = get_mediauri(filename)
    output_dir = os.path.join(TMP_DIR, os.path.basename(fileuri))

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
    app.run(debug=True, host='0.0.0.0', threaded=True)
