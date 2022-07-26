"""This module implements function to split an MP3 recording in multiple
   parts based on different track marker patterns."""
from curses.ascii import isalpha
from pathlib import Path
import os
from collections import namedtuple, defaultdict
from itertools import zip_longest
from enum import Enum
from pprint import pprint
import re
from typing import List
from tqdm import tqdm
from pydub import AudioSegment
import subprocess
import eyed3

# Recording contain the mp3 path and the track marker file path
SegmentedRecord = namedtuple('SegmentedRecord', ['record_name', 'mp3_files', 'tmk_files'])
Record = namedtuple('Record', ['record_name', 'mp3_file', 'tmk_file'])


# Track mark patterns
Pattern = Enum('Pattern', ["IMPORTANT_THOUGHT",
                           "IMPORTANT_THOUGHT_LONG",
                           "IMPORTANT_CONVERSATION",
                           "CONFIDENTIAL",
                           ])

# How many track mark to jump over when encoutering one of the patterns
PatternSkips = {"IMPORTANT_THOUGHT": 1,
                "IMPORTANT_THOUGHT_LONG": 2,
                "IMPORTANT_CONVERSATION": 4,
                "CONFIDENTIAL": 5,
                }

PatternTime = {"IMPORTANT_THOUGHT": 60,
               "IMPORTANT_THOUGHT_LONG": 120,
                }

IMPORTANT_THOUGHT = 1
IMPORTANT_THOUGHT_LONG = 2
IMPORTANT_CONVERSATION = 3
CONFIDENTIAL = 4

# Time to save (in seconds) depending on the track mark pattern used
IMPORTANT_THOUGHT_TIME = 120
IMPORTANT_THOUGHT_LONG_TIME = 600

# Time interval object
TimeInterval = namedtuple('TimeInterval', ['start', 'end', 'type'])

def read_track_markers(filename: Path) -> list:
    """This functions open the TMK file linked to the MP3 and returns
       all the track marker in it in a list of timestamps"""
    with open(filename, 'r', encoding="utf-8-sig") as track_marker_file:
        lines = track_marker_file.readlines()
        track_markers = []
        for line in lines:
            track_markers.append(line.strip())
        return track_markers

def track_mark_interval_to_seconds(first, second):
    """This function converts the interval between two track markers to seconds"""
    second_converted = track_mark_to_seconds(second)
    if first is None:
        return second_converted

    first_converted = track_mark_to_seconds(first)
    return second_converted - first_converted

def track_mark_to_seconds(track_mark):
    """This function converts a track mark to seconds"""
    return float(track_mark[1:6]) * 60 + float(track_mark[7:12])

def seconds_to_track_marker(seconds):
    """This function converts seconds to a track marker"""
    minutes = int(seconds // 60)
    seconds = seconds % 60
    m_str = f"{minutes:05}"
    s_str = f"{seconds:05.2f}"
    return f"[{m_str}:{s_str}]"

def get_windows(track_marks, interval=30):
    """This function returns a list of the number of track marks
       within the window of width INTERVAL"""
    windows = []
    total_time = 0
    track_mark_counter = 0
    index = 0
    reset = True
    while index < len(track_marks):
        if track_mark_counter <= 3:
            if reset:
                reset = False
            else:
                total_time += track_mark_interval_to_seconds(track_marks[index-1], track_marks[index])
            index += 1

        if track_mark_counter >= 4:
            windows.append(Pattern(track_mark_counter))
            # Depending on the amount of track markers detected in a row,
            # the next track marker may get skipped since it belongs to this group
            if track_mark_counter > 2:
                index += 1
            track_mark_counter = 0
            total_time = 0
            reset = True
        elif total_time > interval:
            # Move the index back once since we found a new group of track markers
            index -= 1
            windows.append(Pattern(track_mark_counter))
            # Depending on the amount of track markers detected in a row,
            # the next track marker may get skipped since it belongs to this group
            if track_mark_counter > 2:
                index += 1
            track_mark_counter = 0
            total_time = 0
            reset = True
        else:
            track_mark_counter += 1

    # Last track marker group may exit the loop without being treated if they
    # reach the end of the list of track marker
    if track_mark_counter > 0:
        windows.append(Pattern(track_mark_counter))

    return windows

def find_track_mark_patterns(track_marks, maxTimeInterval=30):
    """This function finds the track markers pattern in the TMK file.
       List of possible patterns:
       1. T: marks the last X minutes as important
       2. TT: marks the last Y minutes as important
       3. TTT-T marks whatever is in between the three first and last track mark as important
       4. TTTT-T marks whatever is in between the four first and last track mark as confidential
          (aka. must be deleted if it is included in any other recording via overlapping)"""
    windows = get_windows(track_marks, maxTimeInterval)
    # Rename the window and create the appropriate time interval for each segment
    time_intervals = []
    index = 0
    previous_was_confidential = False
    for window in windows:
        # If the previous part was confidential we don't want to be able to save it accidently as
        # part of an important thought we had minutes later
        if not previous_was_confidential:
            minimum = 0
        else:
            minimum = track_mark_to_seconds(track_marks[index-1])
            previous_was_confidential = False

        if window == Pattern.IMPORTANT_THOUGHT or window == Pattern.IMPORTANT_THOUGHT_LONG:
            start = max(minimum, track_mark_to_seconds(track_marks[index]) - PatternTime[window.name])
            end = track_mark_to_seconds(track_marks[index])
            time_intervals.append(TimeInterval(start, end, Pattern(window)))
        elif window == Pattern.IMPORTANT_CONVERSATION:
            # Start at the last track mark of the group of 3
            start = track_mark_to_seconds(track_marks[index + 2])
            end = track_mark_to_seconds(track_marks[index + 3])
            time_intervals.append(TimeInterval(start, end, Pattern(window)))
        elif window == Pattern.CONFIDENTIAL:
            # Start at the last track mark of the group of 4
            start = track_mark_to_seconds(track_marks[index + 3])
            end = track_mark_to_seconds(track_marks[index + 4])
            time_intervals.append(TimeInterval(start, end, Pattern(window)))
            previous_was_confidential = True
        else:
            raise ValueError("Invalid number of track markers detected")
        # Skip N markers based on the pattern we just analyzed
        index += PatternSkips[window.name]
    return time_intervals

def concatenate_audio_files(audio_file_paths: List[Path], output_path: Path, verbose=1):
    """This functions concatenates multiple audio files in a single using pydub"""
    if verbose > 0:
        print("Concatenating audio files...")
        audio_file_paths = tqdm(audio_file_paths)
    # Create the output file
    output_file = open(output_path, "wb")
    for audio_file_path in audio_file_paths:
        # Concatenate mp3 file using cat subprocess
        subprocess.run(["cat", str(audio_file_path)], stdout=output_file, check=True)
    if verbose > 0:
        print("Audio files concatenated.")
    output_file.close()

def concatenate_track_marker_files(record, output_path: Path, verbose=1):
    """This functions concatenates multiple track marker files in a single file"""
    if verbose > 0:
        print("Concatenating track marker files...")
        mp3_track_pair_path = tqdm(zip_longest(record.mp3_files, record.tmk_files))
    # Create the output file
    total_time = 0
    first_file = True
    with open(output_path, "w", encoding="utf-8-sig") as output_file:
        for mp3_file_path, track_markers_path in mp3_track_pair_path:
            # Add the track marker from each file in the new track marker file
            with open(track_markers_path, 'r', encoding="utf-8-sig") as track_markers_file:
                if first_file:
                    first_file = False
                    output_file.write(track_markers_file.read())
                else:
                    # Add total time to every track marker of this file
                    track_markers_file.seek(0)
                    for track_marker_line in track_markers_file:
                        # Check if last line of file (TX660 puts empty line at the end)
                        if track_marker_line.strip() == '':
                            break

                        # Create new track marker with added total time
                        orig_track_mark_seconds = track_mark_to_seconds(track_marker_line.strip())
                        new_track_mark_seconds = orig_track_mark_seconds + total_time
                        new_track_mark_line = seconds_to_track_marker(new_track_mark_seconds)
                        output_file.write(new_track_mark_line + "\n")

                # Get the track lenght of the mp3 file and add it to the total time
                track_length = eyed3.load(mp3_file_path).info.time_secs
                total_time += track_length

    if verbose > 0:
        print("Track marker files concatenated.")

def search_and_combine_recordings(path: Path):
    """Returns a list containing all the recording in a folder.
       Renames the recordings to be unique and concatenates them in a single file."""
    file_pairs = defaultdict(lambda: defaultdict(list))
    # Group .mp3 and .tmk that have the same filename prefix together
    for entry in path.iterdir():
        if entry.is_file():
            match = re.search(r"([^_]+)_+[^_]+_", entry.name)
            if match:
                _, file_extension = os.path.splitext(entry.name)
                file_pairs[match.group(1)][file_extension].append(entry)
    # Combine the recordings
    temp_records = []
    for key, value in file_pairs.items():
        temp_records.append(SegmentedRecord(record_name=key, mp3_files=value[".mp3"], tmk_files=value[".tmk"]))

    # For each recording, merge the .mp3 and .tmk files
    final_records = []
    for record in temp_records:
        # New record name
        new_mp3_path = path.joinpath(record.record_name + "_merged" + ".mp3")
        new_tmk_path = path.joinpath(record.record_name + "_merged" + ".tmk")
        # Check if it is segmented or not
        if len(record.mp3_files) > 1:
            # Sort the files so they are merged in the correct order
            record.mp3_files.sort(key=lambda x: x.name)
            record.tmk_files.sort(key=lambda x: x.name)
            concatenate_audio_files(record.mp3_files, new_mp3_path)
            concatenate_track_marker_files(record, new_tmk_path)
            # Delete old files
            for mp3_file, tmk_file in zip_longest(record.mp3_files, record.tmk_files):
                try:
                    mp3_file.unlink(missing_ok=True)
                    tmk_file.unlink(missing_ok=True)
                except AttributeError:
                    pass
        else:
            # Rename the files to the record name
            record.mp3_files[0].rename(new_mp3_path)
            record.tmk_files[0].rename(new_tmk_path)
        # Add the new recording to the list
        final_records.append(Record(record_name=record.record_name,
                                    mp3_file=new_mp3_path,
                                    tmk_file=new_tmk_path))

    return final_records

def split_audio_based_on_track_marks_pattern(record):
    """Splits the mp3 file into segments based on track marker pattern"""
    # Get the track marks pattern
    track_marks = read_track_markers(record.tmk_file)
    track_marks_patterns = find_track_mark_patterns(track_marks)
    # Split the mp3 file into segments
    split_audio_file_into_segments(record, track_marks_patterns)

def split_audio_file_into_segments(record, track_marks_patterns):
    """Splits the mp3 file into segments based on track marker pattern"""
    # Split the mp3 file into segments
    index_of_types = {Pattern.IMPORTANT_THOUGHT: 0, Pattern.IMPORTANT_THOUGHT_LONG: 0, Pattern.IMPORTANT_CONVERSATION: 0}
    for track_marks_pattern in track_marks_patterns:
        segment_type = track_marks_pattern.type
        if segment_type == Pattern.CONFIDENTIAL:
            continue
        index_of_types[segment_type] += 1
        # Create new mp3 segment using ffmpeg subprocess
        timestamps = [track_mark_to_ffmpeg_timestamps(track_mark_seconds) for track_mark_seconds in track_marks_pattern[0:2]]
        output_file_name = record.mp3_file.parent.joinpath(record.record_name + "_" + segment_type.name + str(index_of_types[segment_type]) + ".mp3")
        subprocess.run(["ffmpeg", "-i", record.mp3_file.resolve(), "-ss", timestamps[0], "-to", timestamps[1], "-acodec", "copy", output_file_name.resolve()], check=True)

def track_mark_to_ffmpeg_timestamps(track_mark_seconds):
    """Converts a track marker to ffmpeg timestamps"""
    hours = int(track_mark_seconds // 3600)
    minutes = int((track_mark_seconds % 3600) // 60)
    seconds = int(track_mark_seconds % 60)
    return f"{hours}:{minutes}:{seconds}"

if __name__ == '__main__':
    # Get all mp3 files in the current directory and tuple them with their according TMK file
    # recordings = [Record(*recording) for recording in zip(list(Path.cwd().glob('*.mp3')), list(Path.cwd().glob('*.tmk')))]
    #print(search_and_combine_recordings(Path.cwd()))
    # for recording in recordings:
        # pprint(find_track_mark_patterns([ "[00000:01.00]",
        #                              "[00000:02.00]",
        #                              "[00000:03.00]",
        #                              "[00000:10.00]",
        #                              "[00000:11.00]",
        #                              "[00000:45.00]",
        #                              "[00000:47.00]",
        #                              "[00002:08.00]",
        #                              "[00002:09.00]",
        #                              "[00002:10.00]",
        #                              "[00002:11.00]",
        #                              "[00002:30.00]",
        #                              "[00010:30.00]",
        #                              "[00012:30.00]",
        #                              "[00012:31.00]",
        #                              "[00012:32.00]",
        #                              "[00013:30.00]",]))

    # mp3s = [Path.cwd().joinpath("sample4.mp3"), Path.cwd().joinpath("sample5.mp3")]
    # concatenate_audio_files(mp3s, Path.cwd().joinpath("test_concatenated.mp3"))
    # tmks = [Path.cwd().joinpath("test1.tmk"), Path.cwd().joinpath("test2.tmk")]
    # concatenate_track_marker_files(tmks, Path.cwd().joinpath("test_concatenated.tmk"))

    recordings = search_and_combine_recordings(Path.cwd().joinpath("Real test").joinpath("23 Jul 2022"))
    for recording in recordings:
        split_audio_based_on_track_marks_pattern(recording)
