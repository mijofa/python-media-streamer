#!/usr/bin/python3
import flask
import json
import subprocess
import os.path
import time

# FIXME: These are mostly just assumed by grepping ffprobe -formats & -codecs for each of the things mentioned at
#        https://developers.google.com/cast/docs/media
supported_codecs = {
    'container': ['aac', 'matroska,webm', 'mov,mp4,m4a,3gp,3g2,mj2', 'mp3', 'mp4', 'wav', 'webm', 'webm_chunk', 'webm_dash_manifest'],
    'video': ['h264', 'vp8'],
    'audio': ['aac', 'aac_latm', 'flac', 'mp3', 'mp3adu', 'mp3on4', 'opus', 'vorbis'],
}

ffmpeg_proc = None

app = flask.Flask("python-media-streamer")

@app.route('/')
def index():
  return "Indexing isn't supported yet"

@app.route('/watch/<path:filename>')
def watch(filename):
    # FIXME: So this works as a proof-of-concept, but I'd like to generate the m3u file in Python, then generate each chunk as requested, using -ss or similar to offset each conversion and so on.
    # FIXME: HLS is not supported out of the box, so should probably give up on it and use something else. MPEG-DASH? Direct mp4 files?
    #        If I have to use HLS, investigate hls.js, or perhaps shaka-player? Pretty sure the Chromecast, and mobile apps will support HLS OOTB, but Chrome desktop does not.
    filename = '/srv/media/Video/' + filename
    assert os.path.exists(filename) and not os.path.isdir(filename)
    # FIXME: In some future version of Python3, universal_newlines=True becomes text=True
    codec_checker = subprocess.Popen(stdout=subprocess.PIPE,universal_newlines=True,args=[
        'ffprobe','-v','error',
        '-show_entries','stream=codec_name,codec_type,channels:format=format_name',
        '-print_format','json',
        filename])
    codec_info = json.load(codec_checker.stdout)
    assert codec_checker.wait() == 0
    assert len(codec_info['streams']) <= 2
    copy_audio = copy_video = False
    for stream in codec_info['streams']:
        if stream['codec_type'] == 'audio' and stream['codec_name'] == 'aac' and stream['channels'] > 2:
            # A Chromecast software update removed support for AAC streams with more than 2 channels
            copy_audio = False
        elif stream['codec_type'] == 'audio' and stream['codec_name'] in supported_codecs['audio']:
            copy_audio = True
        elif stream['codec_type'] == 'video' and stream['codec_name'] in supported_codecs['video']:
            copy_video = True

#ffmpeg -rtsp_transport tcp -i ${INPUT} ${LACKING_AUDIO} -acodec ${DEFAULT_AUDIO} -vcodec ${DEFAULT_VIDEO} -hls_list_size 2 -hls_init_time 1 -hls_time 1 -hls_flags delete_segments ${OUTPUT_PATH}${OUTPUT}.m3u8
    # If we're already transcoding something, kill it and wait
    global ffmpeg_proc
    if ffmpeg_proc:
        ffmpeg_proc.kill()
        ffmpeg_proc.wait()
        ffmpeg_proc = None

    ffmpeg_proc = subprocess.Popen(stdin=subprocess.DEVNULL,args=[
        'ffmpeg', '-loglevel','error', '-i',filename, 
        '-acodec','copy' if copy_audio else 'mp3',   '-vcodec','copy' if copy_video else 'h264',
        '-segment_list_flags','+live', '-hls_flags','delete_segments',
        '/tmp/ffmpeg-temp/video.m3u8'
    ])
    time.sleep(1)  # Wait for ffmpeg to actually start so we don't just start replaying the last video

    if copy_audio and copy_video and codec_info['format']['format_name'] in supported_codecs['container']:
        return "No transcoding to be done"
    else:
        # Wait, Chrome doesn't support HLS out of the box? Shit! What about MPEG-DASH? Find something it supports out-of-the-box
        return """<!doctype html><html>
            <head><script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script></head>
            <body>
                <video id="video" controls autoplay />
                <script>
                    var video = document.getElementById("video");
                    if(Hls.isSupported()) {
                      var hls = new Hls({maxBufferLength: 500, manifestLoadingTimeOut: 20000, levelLoadingTimeOut: 20000, fragLoadingTimeOut: 120000});
                      hls.loadSource("/hls/video.m3u8");
                      hls.attachMedia(video);
                      hls.on(Hls.Events.MANIFEST_PARSED,function() {
                        video.play();
                    });
                   }
                </script>
            </body>
        </html>"""
#        return '<!doctype html><html><body><video controls><source src="/hls/video.m3u8" type="application/x-mpegURL"></video></body></html>'

@app.route('/hls/<path:filename>')
def hls(filename):
    return flask.send_from_directory('/tmp/ffmpeg-temp/', filename, cache_timeout=1)

if __name__ == "__main__":
    app.run(debug=True)
