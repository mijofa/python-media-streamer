#!/usr/bin/python3
import glob
import json
import multiprocessing
import operator
import os
import signal
import subprocess
import sys
import urllib.parse

import flask

# Emby's ffmpeg invocation when watching a movie from Chrome Desktop on Debian:
#      /opt/emby-server/bin/ffmpeg -f matroska,webm -i file:/srv/media/Video/TV/Stitchers/S03E02.mkv -threads 0 -map 0:0 -map 0:1 -map -0:s -codec:v:0 libx264 -vf scale=trunc(min(max(iw\,ih*dar)\,1920)/2)*2:trunc(ow/dar/2)*2 -pix_fmt yuv420p -preset veryfast -crf 23 -maxrate 4148908 -bufsize 8297816 -profile:v high -level 4.1 -x264opts:0 subme=0:me_range=4:rc_lookahead=10:me=dia:no_chroma_me:8x8dct=0:partitions=none -force_key_frames expr:if(isnan(prev_forced_t),eq(t,t),gte(t,prev_forced_t+3)) -copyts -vsync -1 -codec:a:0 copy -f segment -max_delay 5000000 -avoid_negative_ts disabled -map_metadata -1 -map_chapters -1 -start_at_zero -segment_time 3 -individual_header_trailer 0 -segment_format mpegts -segment_list_type m3u8 -segment_start_number 0 -segment_list /var/lib/emby/transcoding-temp/f435d247a8462ffd19925d38e555451b.m3u8 -y /var/lib/emby/transcoding-temp/f435d247a8462ffd19925d38e555451b%d.ts  # noqa: E501

### FIXME: These are mostly just assumed by grepping ffprobe -formats & -codecs for each of the things mentioned at
###        https://developers.google.com/cast/docs/media
###        Also Emby outputs in matroska,webm so I *know* that's supported
## supported_codecs = {
##     'container': ['aac', 'mp3', 'mp4', 'wav', 'webm', 'webm_chunk', 'matroska,webm'],
##     'video': ['h264', 'vp8'],  # Chromecast Ultra also supports ['hevc', 'vp9']
##     'audio': ['aac', 'flac', 'mp3', 'opus', 'vorbis'],
## }


def probe(fileuri: str):
    """Probe for codec info and generic track metadata"""
    # FIXME: Add a reasonable timeout. What's reasonable?
    ffprobe = subprocess.run(stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, universal_newlines=True, check=True, args=[
        'ffprobe', '-loglevel', 'error',
        '-show_entries', 'stream=index,codec_name,codec_type,channels,r_frame_rate:stream_tags:format=format_name,duration',
        '-print_format', 'json=compact=1',
        '-i', fileuri])
    assert ffprobe.returncode == 0  # check=True should've already taken care of this.
    probed_info = json.loads(ffprobe.stdout)
    assert len(probed_info['streams']) <= 2, "Subtitles & multiple audio/video tracks are currently unsupported"
    container_info = {'format': probed_info['format']['format_name'],
                      'duration': float(probed_info['format']['duration'])}  # Why isn't ffprobe giving us a float here?
    v_streams = []
    a_streams = []
    # Note the index here will have the first "stream" is video and the second "stream" is audio,
    # but when reffering to them later I refer to them as the first "video stream" and the first "audio stream".
    # This inconsistency is confusing, so by making sure it's sorted by the index first
    # I should be able to avoid storing the index and keep the confusion here and only here.
    for stream in sorted(probed_info['streams'], key=lambda d: d.get('index')):
        if stream['codec_type'] == 'video':
            fps = operator.truediv(*(int(i) for i in stream['r_frame_rate'].split('/')))
            # FIXME: Is there any identifiers worth adding here?
            v_streams.append({'codec': stream['codec_name'], 'fps': fps})
        elif stream['codec_type'] == 'audio':
            # FIXME: Pretty sure I've seen some sort of labels on audio & subtitle streams.
            #        Maybe that's just put together from the tags?
            a_streams.append({'codec': stream['codec_name'],
                              # Need to get channels because aac is supported by Chromecast, but not with more than 2 channels,
                              # and I intend to (if possible) codec copy when the original is already supported.
                              'channels': stream['channels'],
                              # There might be no language tag, or there might be no tags at all
                              # FIXME: Should I just put the entire 'tags' section here?
                              'language': stream.get('tags', {}).get('language', '')})
        else:
            raise NotImplementedError("Streams of type {} are not supported".format(stream['codec_type']))
    print(v_streams, a_streams)
    return {'container': container_info, 'video': v_streams, 'audio': a_streams}


def get_duration(fileuri: str):
    # FIXME: Can ffmpeg just tell us the duration as it starts up?
    # FIXME: Add a reasonable timeout. What's reasonable?
    # FIXME: Technically each track within the media file can have a different duration.
    probe = subprocess.check_output(
        stdin=subprocess.DEVNULL, universal_newlines=True, args=[
            'ffprobe', '-loglevel', 'error',
            '-show_entries', 'format=duration',
            '-print_format', 'json=compact=1',
            '-i', fileuri])
    probed_info = json.loads(probe)
    assert "format" in probed_info
    assert "duration" in probed_info["format"]
    assert len(probed_info.keys()) == 1
    assert len(probed_info["format"].keys()) == 1
    return float(probed_info["format"]["duration"])


def get_caption_tracks(fileuri: str):
    caption_tracks = {}

    probe = subprocess.check_output(
        stdin=subprocess.DEVNULL, universal_newlines=True, args=[
            'ffprobe', '-loglevel', 'error', '-print_format', 'json',
            fileuri, '-select_streams', 's',
            '-show_entries', 'stream=index:stream_tags'])
    probed_info = json.loads(probe)
    assert "streams" in probed_info
    for track in probed_info["streams"]:
        if "language" not in track["tags"]:
            track["tags"]["language"] = "und"
            if "title" not in track["tags"]:
                track["tags"]["title"] = "Undetermined"
        if "title" not in track["tags"]:
            track["tags"]["title"] = track["tags"]["language"].title()  # FIXME: Make a better title
        caption_tracks["native:{}".format(track["index"])] = track["tags"]

    parseduri = urllib.parse.urlparse(fileuri)
    if parseduri.scheme in ('', 'file'):
        # Find every file with just a different extension
        for ind, sub_file in enumerate(glob.glob("{}.*".format(parseduri.path.rpartition(os.path.extsep)[0]))):
            ext = sub_file.rpartition(os.path.extsep)[-1]
            # FIXME: Can ffmpeg support sub/idx?
            if ext.lower() in ('srt', 'vtt'):
                caption_tracks["supplementary:{}".format(ext)] = {
                    "title": ext.upper(),
                    "language": "und"}  # I think this is the standard for "undetermined"

    return json.dumps(caption_tracks)


def get_captions(fileuri: str, index: str):
    input_type, stream_id = index.split(':')
    if input_type == 'supplementary':
        fileuri = os.path.extsep.join((fileuri.rpartition(os.path.extsep)[0], stream_id))
        stream_map = 's'
    elif input_type == "native":
        # FIXME: Understand this better
        #        I think the '0:' means "the first file" or similar.
        #        I think if I were using larger mpeg-ts streams (like DVB-T) it would get more complicated.
        stream_map = "0:{}".format(stream_id)

    # FIXME: In all my testing, ffmpeg did this job really quick,
    #        but perhaps I should turn this into a generator so as to not assume that will be the case.
    vtt_result = subprocess.check_output(
        stdin=subprocess.DEVNULL,
        args=[
            'ffmpeg', '-loglevel', 'error', '-nostdin',
            '-i', fileuri,  # Everything after this only applies to the output
            '-codec:s', 'webvtt', '-f', 'webvtt',  # WebVTT is all that's supported, so no need to get smart here
            '-map', stream_map,
            'pipe:1'])

    return vtt_result


def _wait_for_manifest(output_dir: str):
    # FIXME: I should probably at least put a time.sleep(0.1) here
    # FIXME: Wait for a couple of segments rather than just wait for the manifest.
    #        Does ffmpeg perhaps do that already?
    while not os.path.isfile(os.path.join(output_dir, 'hls-manifest.m3u8')):
        pass


def start_transcode(output_dir: str, fileuri: str):
    # FIXME: Is it even worth doing HLS if this is how we have to do it?
    # FIXME: Perhaps just turn this into an iterable generator of a single mp4/ts stream and do streaming "old-school"
    if not os.path.isdir(output_dir):
        os.mkdir(output_dir)

    # Not using run() because I don't want to wait around for ffmpeg to finish,
    # annoyingly that means I don't get check=True and have to sort out my own returncode handling, if any.
    # FIXME: Implement some sort of cleanup so we don't keep transcoding if the user goes away.
    ffmpeg = subprocess.Popen(
        stdin=subprocess.DEVNULL, universal_newlines=True,
        cwd=output_dir, args=[
            'ffmpeg', '-loglevel', 'error', '-nostdin',
            '-i', fileuri,  # Everything after this only applies to the output
            '-codec:a', 'libmp3lame', '-codec:v', 'libx264',  # FIXME: Copy the codec when it's already supported
            '-f', 'hls', '-hls_playlist_type', 'vod',
            '-hls_segment_filename', 'hls-segment-%d.ts',  # I would like to 0-pad the number, but I don't know how far to pad it
            # FIXME: Did ffmpeg remove the temp_file flag?
            # # With Emby I was seeing instances of what looked like the browser caching ahead of what the server had transcoded
            # # I suspect that's because Emby wasn't using this temp_file flag, but I've not been able to confirm that in any way.
            # '-hls_flags', 'temp_file',
            # FIXME: Add the single_file flag?
            'hls-manifest.m3u8'])
    timer = multiprocessing.Process(target=_wait_for_manifest, args=(output_dir,))
    timer.start()
    timer.join(timeout=5)  # Wait for process to end or 5 seconds, whichever comes first.

    if ffmpeg.poll():
        # I know there's subprocess.run().check_returncode() but Popen doesn't have similar, so I gotta do it myself.
        #
        # I'm only defining this variable instead of putting it all on the raise line so that the backtrace looks nicer
        err = ffmpeg.stderr.read().decode()
        print(err, file=sys.stderr, flush=True)
        FfmpegError = subprocess.CalledProcessError(
            returncode=ffmpeg.returncode,
            cmd=ffmpeg.args,
            # output=ffmpeg.stdout.read(),  # I've already captured the stdout, so this is useless.
            stderr=err,
        )
        raise FfmpegError

    if timer.is_alive():  # Shit, we timed out without finding a manifest
        # Cleanup the timer, and ffmpeg
        timer.terminate()
        # ffmpeg doesn't acknowledge a SIGTERM, but it does die on SIGINT
        ffmpeg.send_signal(signal.SIGINT)
        # If that didn't work, SIGKILL it
        try: ffmpeg.wait(timeout=2)                      # noqa: E701
        except subprocess.TimeoutExpired: ffmpeg.kill()  # noqa: E701

        raise FileNotFoundError('No manifest file was found after ffmpeg initialisation')


def get_manifest(output_dir: str, fileuri: str):
    if not os.path.isfile(os.path.join(output_dir, 'hls-manifest.m3u8')):
        start_transcode(output_dir, fileuri)

    return flask.send_from_directory(output_dir, 'hls-manifest.m3u8', mimetype='application/x-mpegURL')


def get_segment(output_dir: str, index: int):
    return flask.send_from_directory(output_dir, 'hls-segment-{index:d}.ts'.format(index=index), mimetype='video/mp2t')
