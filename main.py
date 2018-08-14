#!/usr/bin/python3
import flask
import json
import subprocess
import os.path
import time

import ffmpeg

app = flask.Flask("python-media-streamer")

@app.route('/')
def index():
  return "Indexing isn't supported yet"

@app.route('/watch/<path:filename>/player.html')
def watch(filename):
    filepath = '/srv/media/Video/' + filename
    assert os.path.exists(filepath) and not os.path.isdir(filepath)
    fileuri = 'file:' + filepath
    del filename
    del filepath

    return """<!doctype html><html>
        <head><script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script></head>
        <body>
            <video id="video" controls autoplay />
            <script>
                var video = document.getElementById("video");
                if(Hls.isSupported()) {
                  var hls = new Hls({maxBufferLength: 500, manifestLoadingTimeOut: 20000, levelLoadingTimeOut: 20000, fragLoadingTimeOut: 120000});
                  hls.loadSource("manifest.m3u8");
                  hls.attachMedia(video);
                  hls.on(Hls.Events.MANIFEST_PARSED,function() {
                    video.play();
                });
               }
            </script>
        </body>
    </html>"""

@app.route('/watch/<path:filename>/manifest.m3u8')
def manifest(filename):
    # FIXME: Don't copy-paste this shit
    filepath = '/srv/media/Video/' + filename
    assert os.path.exists(filepath) and not os.path.isdir(filepath)
    fileuri = 'file:' + filepath
    del filename
    del filepath

    duration = ffmpeg.probe(fileuri)['container']['duration']
    return flask.Response(ffmpeg.generate_manifest(duration), mimetype='application/x-mpegURL')

@app.route('/watch/<path:filename>/hls-segment.ts')
def hls_segment(filename):
    # FIXME: Don't copy-paste this shit
    filepath = '/srv/media/Video/' + filename
    assert os.path.exists(filepath) and not os.path.isdir(filepath)
    fileuri = 'file:' + filepath
    del filename
    del filepath

    # FIXME: Assert that there's no more than one of each argument
    return flask.Response(ffmpeg.get_segment(fileuri=fileuri,
                                             index=int(flask.request.args['index']),
                                             offset=float(flask.request.args['offset']),
                                             length=float(flask.request.args['length'])),
                          mimetype='video/mp2t')

if __name__ == "__main__":
    app.run(debug=True)
