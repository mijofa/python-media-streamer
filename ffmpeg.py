#!/usr/bin/python3
import json
import subprocess
import math

# Emby's ffmpeg invocation when watching a movie from Chrome Desktop on Debian:
#      /opt/emby-server/bin/ffmpeg -f matroska,webm -i file:/srv/media/Video/TV/Stitchers/S03E02.mkv -threads 0 -map 0:0 -map 0:1 -map -0:s -codec:v:0 libx264 -vf scale=trunc(min(max(iw\,ih*dar)\,1920)/2)*2:trunc(ow/dar/2)*2 -pix_fmt yuv420p -preset veryfast -crf 23 -maxrate 4148908 -bufsize 8297816 -profile:v high -level 4.1 -x264opts:0 subme=0:me_range=4:rc_lookahead=10:me=dia:no_chroma_me:8x8dct=0:partitions=none -force_key_frames expr:if(isnan(prev_forced_t),eq(t,t),gte(t,prev_forced_t+3)) -copyts -vsync -1 -codec:a:0 copy -f segment -max_delay 5000000 -avoid_negative_ts disabled -map_metadata -1 -map_chapters -1 -start_at_zero -segment_time 3 -individual_header_trailer 0 -segment_format mpegts -segment_list_type m3u8 -segment_start_number 0 -segment_list /var/lib/emby/transcoding-temp/f435d247a8462ffd19925d38e555451b.m3u8 -y /var/lib/emby/transcoding-temp/f435d247a8462ffd19925d38e555451b%d.ts

### FIXME: These are mostly just assumed by grepping ffprobe -formats & -codecs for each of the things mentioned at
###        https://developers.google.com/cast/docs/media
##supported_codecs = {
##    'container': ['aac', 'mp3', 'mp4', 'wav', 'webm', 'webm_chunk', 'matroska,webm'],  # Emby outputs in matroska,webm so I *know* that's supported
##    'video': ['h264', 'vp8'],  # Chromecast Ultra also supports ['hevc', 'vp9']
##    'audio': ['aac', 'flac', 'mp3', 'opus', 'vorbis'],
##}

def probe(fileuri: str):
    """Probe for codec info and generic track metadata"""
    # FIXME: Add a reasonable timeout. What's reasonable?
    ffprobe = subprocess.run(stdout=subprocess.PIPE,universal_newlines=True,check=True,args=[
        'ffprobe','-v','error',
        '-show_entries','stream=index,codec_name,codec_type,channels:stream_tags:format=format_name,duration',
        '-print_format','json=compact=1',
        '-i',fileuri])
    assert ffprobe.returncode == 0  # check=True should've already taken care of this.
    probed_info = json.loads(ffprobe.stdout)
    assert len(probed_info['streams']) <= 2, "Subtitles & multiple audio/video tracks are currently unsupported"
    container_info = {'format': probed_info['format']['format_name'],
                      'duration': float(probed_info['format']['duration'])}  # Why isn't ffprobe giving us a float here?
    v_streams = []
    a_streams = []
    # Note the index here will have the first "stream" is video and the second "stream" is audio,
    # but when reffering to them later I refer to them as the first "video stream" and the first "audio stream".
    # This inconsistency is confusing, so by making sure it's sorted by the index first I should be able to avoid storing the index and keep the confusion here and only here.
    for stream in sorted(probed_info['streams'], key=lambda d: d.get('index')):
        if stream['codec_type'] == 'video':
            # FIXME: Is there any identifiers worth adding here?
            v_streams.append({'codec': stream['codec_name']})
        elif stream['codec_type'] == 'audio':
            # FIXME: Pretty sure I've seen some sort of labels on audio & subtitle streams, is that just put together from the tags?
            a_streams.append({'codec': stream['codec_name'],
                              'channels': stream['channels'],  # Need to specify this because aac is supported by Chromecast, but not with more than 2 channels
                              'language': stream.get('tags', {}).get('language', '')})  # There might be no language tag, or there might be no tags at all
                              # FIXME: Should I just put the entire 'tags' section here?
        else:
            raise NotImplementedError("Streams of type {} are not supported".format(stream['codec_type']))
    return {'container': container_info, 'video': v_streams, 'audio': a_streams}

#def find_keyframes(fileuri: str, video_stream_id: int = 0):
#    """Find timestamps for all keyframes in the selected video stream"""
#    ffprobe = subprocess.run(stdout=subprocess.PIPE,universal_newlines=True,check=True,args=[
#        'ffprobe','-v','error',
#        '-skip_frame','nokey',  # We want to know where all the keyframes are, but we don't care about any of the other frame timestamps
#        '-show_entries','frame=best_effort_timestamp_time',
#        '-print_format','compact=nokey=1:print_section=0',
#        '-select_streams','v:{}'.format(video_stream_id),
#        '-i',fileuri])
#    assert ffprobe.returncode == 0  # check=True should've already taken care of this.
#    keyframes = ffprobe.stdout.split('\n')
#    # FIXME: Should we cast all lines into floats?
#    # FIXME: Is it safe to assume it's already sorted?
#    return keyframes

def generate_manifest(duration: float, segment_length: float = 10):
    segment_count = math.ceil(duration/segment_length)
    m3u = ["#EXTM3U",
           "#EXT-X-VERSION:3",
           "#EXT-X-MEDIA-SEQUENCE:0",
           "#EXT-X-PLAYLIST-TYPE:VOD",
           "#EXT-X-ALLOW-CACHE:YES",
           #"#EXT-X-START:"  # Probably wanna use this to set a save point
           "#EXT-X-TARGETDURATION:{}".format(segment_length),
           ]+["#EXTINF:{segment_duration:0.6f},\nhls-segment.ts?index={index}&offset={offset:0.6f}&length={segment_duration:0.6f}".format(
               segment_duration=segment_length, index=segment_index,
               offset=0 if segment_index == 0 else  # First segment
                      duration - ( segment_length * ( segment_index ) ) if segment_index == segment_count - 1 else  # Last segment
                      segment_length * segment_index)  # All other segments
                          for segment_index in range(0, segment_count)]+[
           "#EXT-X-ENDLIST"]
    return '\n'.join(m3u)


def get_segment(fileuri: str, offset: float, length: float, index: int):
    # Not setting universal_newlines=True because I want the binary output here
    print(length)
    ffmpeg = subprocess.run(stdout=subprocess.PIPE,check=True,args=[
        'ffmpeg', '-loglevel','error', 
        '-ss','{:0.6f}'.format(offset), 
        '-i',fileuri,'-t','{:0.6f}'.format(length),
        '-acodec','mp3',   '-vcodec','h264',  # FIXME: Copy the codec when it's already supported
        '-f','mpegts', '-force_key_frames', '0', 'pipe:1'])
    assert ffmpeg.returncode == 0  # check=True should've already taken care of this.
    return ffmpeg.stdout
