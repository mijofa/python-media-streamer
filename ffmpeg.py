#!/usr/bin/python3
import fcntl
import json
import operator
import os
import signal
import subprocess
import sys

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


def transcode(fileuri: str):
    # Not using run() because I don't want to wait around for ffmpeg to finish,
    # annoyingly that means I don't get check=True and have to sort out my own returncode handling, if any.
    # FIXME: Implement some sort of cleanup so we don't keep transcoding if the user goes away.
    ffmpeg = subprocess.Popen(
        stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, universal_newlines=False,
        args=[
            'ffmpeg', '-loglevel', 'error', '-nostdin',
            '-i', fileuri,  # Everything after this only applies to the output
            '-acodec', 'libmp3lame', '-vcodec', 'libx264',  # FIXME: Copy the codec when it's already supported
            # MP4 container format is not good enough on it's own, it needs to be a fragmented MP4 file for streaming to work.
            # Normally it's suggested to include the faststart flag, but that's not possible with fragmented mp4
            '-f', 'mp4', '-movflags', 'frag_keyframe+empty_moov',
            'pipe:1'])

    print("ffmpeg transcode started")

    # Set stdout to be non-blocking so that I don't have to read it all at once.
    # FIXME: Is there a more pythonic way to do this?
    # FIXME: Pretty sure all of this can be done better with select.select
    fcntl.fcntl(ffmpeg.stdout, fcntl.F_SETFL,
                fcntl.fcntl(ffmpeg.stdout, fcntl.F_GETFL) | os.O_NONBLOCK)  # Get current flags, and add O_NONBLOCK
    try:
        # ffmpeg.stdout never closes, that's weird.
        # NOTE: ffmpeg.returncode is always None unless poll() or wait() has been called
        while ffmpeg.poll() is None:
            data = ffmpeg.stdout.read()
            if data is None:
                # There's no data ready to read
                pass
            elif not data:  # Empty string as opposed to None
                # Command has ended, I'd expect stdout to be closed here, but that's not how subprocess works apparently
                # FIXME: Is is possible to get this when there's still more valid data to come?
                print("ffmpeg transcode has finished")
                break
            else:
                yield data
    except GeneratorExit as e:
        print("ffmpeg transcode cancelled")
        # ffmpeg doesn't die unless we read out all its data, or kill it.
        # When the HTTP request stops, the generator stops being iterated over,
        # so we've stopped reading the data and need to kill it instead.
        #
        # Why doesn't ffmpeg acknowledge a SIGTERM?
        # Ok, it acknowledges SIGINT so we'll go with that.
        ffmpeg.send_signal(signal.SIGINT)

        # If that didn't work, SIGKILL it
        try: ffmpeg.wait(timeout=4)                      # noqa: E701
        except subprocess.TimeoutExpired: ffmpeg.kill()  # noqa: E701

        # Leave a note that it was killed here so the finally block can ignore a bad exit status
        ffmpeg.been_killed = True
    finally:
        # ffmpeg closes stdout before finishing its own cleanup & exit.
        # Need to wait for it to exit in order to actually handle the return code properly.
        # Although if it was intentionally killed earlier, we don't care that it's an unclean death
        #
        # If it's still not dead yet then there will be a TimeoutExpired exception, which we can handle separately.
        if ffmpeg.wait(timeout=1) != 0 and not ffmpeg.__dict__.get('been_killed', False):
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
