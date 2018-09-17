#!/usr/bin/python3
import json
import math
import operator
import os
import subprocess

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
    ffprobe = subprocess.run(stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, universal_newlines=True, check=True, args=[
        'ffprobe', '-loglevel', 'error',
        '-show_entries', 'format=duration',
        '-print_format', 'json=compact=1',
        '-i', fileuri])
    assert ffprobe.returncode == 0  # check=True should've already taken care of this.
    probed_info = json.loads(ffprobe.stdout)
    assert "format" in probed_info
    assert "duration" in probed_info["format"]
    assert len(probed_info.keys()) == 1
    assert len(probed_info["format"].keys()) == 1
    return float(probed_info["format"]["duration"])


def get_manifest(fileuri: str):
    duration = get_duration(fileuri)
    segment_count = math.ceil(duration / 3)
    m3u = ["#EXTM3U",
           "#EXT-X-INDEPENDENT-SEGMENTS",
           "#EXT-X-PLAYLIST-TYPE:VOD",
           "#EXT-X-VERSION:3",
           "#EXT-X-TARGETDURATION:3",
           "#EXT-X-MEDIA-SEQUENCE:0",
           "#EXT-X-ALLOW-CACHE:NO",  # FIXME: Allow caching after some testing has been done
           # "#EXT-X-START:"  # Probably wanna use this to set a save point
           ] + ["#EXTINF:3.000000, nodesc\n"
                "hls-segment-{index}.ts".format(index=segment_index)
                for segment_index in range(0, segment_count)
                ] + ["#EXT-X-ENDLIST"]
    return '\n'.join(m3u)


def get_segment(fileuri: str, index: int):
    (pipe_out, pipe_in) = os.pipe2(os.O_NONBLOCK)

    ## CHROMECAST QUIRKS
    ## These are all the undocumented quirks with Chromecast's HLS implementation that work fine in Chrome on the desktop,
    ## but I still need to work around to get any casting working.
    ##
    ## * Chromecast just completely gives up on the stream if there's any overlap across segments.
    ##   This means I can't (for example) create 10 second segments but only play the first 6 seconds.
    ## * Chromecast gets *really* buggy if there's any gaps between segments, it's more than just a hiccup at each segment,
    ##   but completely unwatchable with constant pauses which last longer than the gap itself does.
    #
    # FIXME: This will *always* report a non-zero exit status because I'm trying to create more than 1 segment,
    #        but only opening 1 output pipe for them.
    # FIXME: Do some actual error reporting.
    ffmpeg = subprocess.Popen(
        stdout=subprocess.DEVNULL,  # stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL, universal_newlines=True,
        pass_fds=(pipe_in,),
        args=[
            'ffmpeg', '-loglevel', 'error',
            # If it's the first index, don't seek at all because seeking to 0 is NOT the same as starting at the beginning.
            # This is doe to some weirdness with certain files that can actually have a start time > 0 and so on.
            ] + (['-accurate_seek', '-ss', str(index * 3)] if index != 0 else []) + [  # noqa: E123
            '-t', '3',
            '-i', fileuri,
            '-map', '0:0', '-map', '0:1',
            # FIXME: Chromecast doesn't support more than 2 channels with AAC codec,
            #        but I'm struggling to make other codecs work at all.
            '-codec:v', 'libx264',
            '-vf', 'scale=trunc(min(max(iw\,ih*dar)\,1920)/2)*2:trunc(ow/dar/2)*2',
            '-pix_fmt', 'yuv420p', '-preset', 'veryfast', '-crf', '23',
            '-maxrate', '4148908', '-bufsize', '8297816', '-profile:v', 'high', '-level', '4.1',
            '-x264opts', 'subme=0:me_range=4:rc_lookahead=10:me=dia:no_chroma_me:8x8dct=0:partitions=none',

            '-codec:a', 'libmp3lame', '-ac', '2', '-ab', '384000', '-af', 'volume=2',

            '-muxdelay', '0', '-max_delay', '5000000',

            # Force a keyframe every 3 seconds, this way there will always be one at the beginning of every 6 second chunk
            '-force_key_frames', 'expr:if(isnan(prev_forced_t),eq(t,t),gte(t,prev_forced_t+3))',
            '-copyts', '-vsync', '-1', '-f', 'segment', '-avoid_negative_ts', 'disabled',
            '-start_at_zero', '-segment_time', '3', '-segment_time_delta', '-{}'.format(index * 3),
            '-individual_header_trailer', '0', '-break_non_keyframes', '1',

            '-segment_format', 'mpegts', '-segment_list_type', 'flat',
            # NOTE: The segment_start_number needs to be the FD number, it doesn't actually affect the contents of the segment,
            #       just filename of the first segment, so "pipe:%d" will match the FD it should go out on.
            '-segment_list', 'pipe:1', '-segment_start_number', str(pipe_in), 'pipe:%d',
        ])

    try:
        while True:
            try:
                data = os.read(pipe_out, 1024)
            except BlockingIOError:
                if ffmpeg.poll() is None:
                    # ffmpeg's still running, there's just no data waiting for us
                    continue
                else:
                    # Ffmpeg's finished, and not closed the fd properly.
                    # This is actually expected, the fd never gets closed properly.
                    break

            yield data
    except GeneratorExit as e:
        # FIXME: Do this cleaner, ffmpeg only actually cleanly shuts down from a SIGINT
        ffmpeg.kill()
        ffmpeg.terminate()
    finally:
        os.close(pipe_in)
        os.close(pipe_out)

    #        'ffmpeg', '-loglevel', 'error', '-nostdin',
    #        '-i', fileuri,  # Everything after this only applies to the output
    #        '-acodec', 'libmp3lame', '-vcodec', 'libx264',  # FIXME: Copy the codec when it's already supported
    #        '-f', 'hls', '-hls_playlist_type', 'vod',
    #        '-hls_segment_filename', 'hls-segment-%d.ts',  # I would like to 0-pad the number, but I don't know how far to pad it
    #        # FIXME: Did ffmpeg remove the temp_file flag?
    #        # # With Emby I was seeing instances of what looked like the browser caching ahead of what the server had transcoded
    #        # # I suspect that's because Emby wasn't using this temp_file flag, but I've not been able to confirm that in any way.
    #        # '-hls_flags', 'temp_file',
    #        # FIXME: Add the single_file flag?
    #        'hls-manifest.m3u8'])
