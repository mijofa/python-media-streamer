#!/usr/bin/python3
import sys
import os.path

import flask

import ffmpeg

app = flask.Flask("python-media-streamer")

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
    return flask.send_file(os.path.join('static', 'player.html'), mimetype='text/html')


@app.route('/watch/<path:filename>/manifest.m3u8')
def manifest(filename):
    fileuri = get_mediauri(filename)

    duration = ffmpeg.probe(fileuri)['container']['duration']
    return flask.Response(ffmpeg.generate_manifest(duration), mimetype='application/x-mpegURL')


# Chromecast requires CORS headers for all media resources, I don't yet understand CORS headers.
# This is just enough to make Chromecast work, haphazardly stolen from https://gist.github.com/blixt/54d0a8bf9f64ce2ec6b8
#
# FIXME: Make sense of CORS headers, and implement them properly.
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response
app.after_request(add_cors_headers)  # noqa: E305


@app.route('/raw_media/<path:filename>')
def raw_media(filename):
    return flask.send_from_directory(media_path, filename)


@app.route('/watch/<path:filename>/hls-segment#<int:index>.ts')
def hls_segment(filename, index):
    fileuri = get_mediauri(filename)

    assert index == int(flask.request.args['index'])

    # FIXME: Assert that there's no more than one of each argument
    return flask.Response(ffmpeg.get_segment(fileuri=fileuri,
                                             index=int(flask.request.args['index']),
                                             offset=float(flask.request.args['offset']),
                                             length=float(flask.request.args['length'])),
                          mimetype='video/mp2t')


if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', threaded=True)
