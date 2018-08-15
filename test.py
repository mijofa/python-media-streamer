#!/usr/bin/python3
import os
import sys
import math
import ffmpeg
input_file = sys.argv[1]
output_dir = sys.argv[2]

segment_length = 10

duration = ffmpeg.probe(input_file)['container']['duration']

print("making dir", output_dir)
os.mkdir(output_dir)
with open(os.path.join(output_dir, 'manifest.m3u8'), 'w') as manifest:
    manifest.write(ffmpeg.generate_manifest(duration, segment_length))

segment_count = math.ceil(duration / segment_length)

for segment_index in range(0, segment_count):
    offset = 0 if segment_index == 0 else duration - (segment_length * (segment_index)) if segment_index == segment_count - 1 else segment_length * segment_index  # noqa: E501
    filename = "hls-segment.ts?index={index}&offset={offset:0.6f}&length={segment_duration:0.6f}".format(
        segment_duration=segment_length, index=segment_index, offset=offset)
    with open(os.path.join(output_dir, filename), 'wb') as segment_file:
        segment_file.write(ffmpeg.get_segment(input_file, offset=offset, length=segment_length, index=segment_index))

## ["#EXTINF:{segment_duration:0.6f},\n"
##  "hls-segment.ts?index={index}&offset={offset:0.6f}&length={segment_duration:0.6f}".format(
##                     segment_duration=segment_length, index=segment_index,
##                     offset=0 if segment_index == 0 else  # First segment
##                     duration - (segment_length * (segment_index)) if segment_index == segment_count - 1 else  # Last segment  # noqa: E131,E501
##                            segment_length * segment_index)  # All other segments
##                                for segment_index in range(0, segment_count)] + [
##            "#EXT-X-ENDLIST"]
##     return '\n'.join(m3u)
##
##
## def get_segment(fileuri: str, offset: float, length: float, index: int):
##     # Not setting universal_newlines=True because I want the binary output here
