#!/usr/bin/python3
import fcntl
import json
import math
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

# def find_keyframes(fileuri: str, video_stream_id: int = 0):
#     """Find timestamps for all keyframes in the selected video stream"""
#     ffprobe = subprocess.run(stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,universal_newlines=True,check=True,args=[
#         'ffprobe','-loglevel','error', '-nostdin',
#         # We want to know where all the keyframes are, but we don't care about any of the other frame timestamps
#         '-skip_frame','nokey',
#         '-show_entries','frame=best_effort_timestamp_time',
#         '-print_format','compact=nokey=1:print_section=0',
#         '-select_streams','v:{}'.format(video_stream_id),
#         '-i',fileuri])
#     assert ffprobe.returncode == 0  # check=True should've already taken care of this.
#     keyframes = ffprobe.stdout.split('\n')
#     # FIXME: Should we cast all lines into floats?
#     # FIXME: Is it safe to assume it's already sorted?
#     return keyframes


def generate_manifest(duration: float, segment_length: float = 10):
    # FIXME: I'm using Flask, Flask has a templating engine, use that?
    segment_count = math.ceil(duration / segment_length)
    m3u = ["#EXTM3U",
           "#EXT-X-VERSION:3",
           "#EXT-X-DISCONTINUITY-SEQUENCE:0",
           "#EXT-X-MEDIA-SEQUENCE:0",
           "#EXT-X-PLAYLIST-TYPE:VOD",
           "#EXT-X-ALLOW-CACHE:YES",
           # "#EXT-X-START:"  # Probably wanna use this to set a save point
           # Target duration *MUST* be at least the length of the longest segment, safer to go slightly higher.
           "#EXT-X-TARGETDURATION:{}".format(segment_length + 1),
           ] + ["{discontinuity}"
                "#EXTINF:{segment_duration:0.6f},\n"
                "hls-segment.ts?index={index}&offset={offset:0.6f}&length={segment_duration:0.6f}".format(
                    segment_duration=segment_length, index=segment_index,
                    discontinuity="#EXT-X-DISCONTINUITY\n" if segment_index != 0 else "",
                    offset=0 if segment_index == 0 else  # First segment
                    duration - (segment_length * (segment_index)) if segment_index == segment_count - 1 else  # Last segment  # noqa: E131,E501
                           segment_length * segment_index)  # All other segments
                               for segment_index in range(0, segment_count)] + [
           "#EXT-X-ENDLIST"]
    return '\n'.join(m3u)


def get_segment(fileuri: str, offset: float, length: float, index: int):
    # Not setting universal_newlines=True because I want the binary output here
    # Not using run() because I want to get the output before the command finishes,
    # annoyingly that means I don't get check=True and have to sort out my own returncode handling.
    ffmpeg = subprocess.Popen(stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, args=[
        'ffmpeg', '-loglevel', 'error', '-nostdin',
        # Seek to the offset, and only play for the length
        '-ss', '{:0.6f}'.format(offset), '-t', '{:0.6f}'.format(length),
        '-i', fileuri,  # Everything after this only applies to the output
        # Set the output's timestamp, otherwise the browser thinks it's already played this part
        '-output_ts_offset', '{:0.6f}'.format(offset),
        # Chromecast with acodec mp3 fails completely
        # Chromecast with acodec aac works for less than 1 second (not an entire segment) and then just stops
        #
        # Is the problem actually the filename? It fails as soon as the 2nd segment starts to download,
        # perhaps the Chromecast isn't liking that both segments have the same filename regardless of the query strings.
        # FIXME: Try Chromecast again with the index included in the filename not just the query string.
        #        Requires updating generate_manifest() above and main.py:manifest()
        # Nope, not the filename. Not the audio stream either. Nor the bitrate
        '-acodec', 'aac', '-vcodec', 'libx264',  # FIXME: Copy the codec when it's already supported
        # FIXME: Do I need to force a key frame? Should I even bother?
        '-f', 'mpegts', '-force_key_frames', '0', 'pipe:1'])
    # Set stdout to be non-blocking so that I don't have to read it all at once.
    # FIXME: Is there a more pythonic way to do this?
    fcntl.fcntl(ffmpeg.stdout, fcntl.F_SETFL,
                fcntl.fcntl(ffmpeg.stdout, fcntl.F_GETFL) | os.O_NONBLOCK)  # Get current flags, and add O_NONBLOCK
    try:
        # ffmpeg.stdout never closes, that's weird.
        while ffmpeg.poll() is None:
            data = ffmpeg.stdout.read()
            if data is None:
                # There's no data ready to read
                pass
            elif not data:
                # Command has ended, I'd expect stdout to be closed here, but that's not how subprocess works apparently
                # FIXME: Is is possible to get this when there's still more valid data to come?
                print("finished segment")
                break
            else:
                yield data
    except GeneratorExit as e:
        print("Segment cancelled")
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
