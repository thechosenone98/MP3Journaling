"""This module implements function to split an MP3 recording in multiple
   parts based on different track marker patterns."""
from pathlib import Path
import os
from collections import namedtuple, defaultdict
from itertools import zip_longest
from enum import Enum
import re
from typing import List
from tqdm import tqdm
import subprocess
import eyed3
from datetime import datetime

# Recording contain the mp3 path and the track marker file path
SegmentedRecord = namedtuple('SegmentedRecord', ['record_name', 'mp3_files', 'tmk_files'])
Record = namedtuple('Record', ['record_name', 'mp3_file', 'tmk_file'])


# Track mark patterns
Pattern = Enum('Pattern', ["IMPORTANT_THOUGHT",
                           "IMPORTANT_THOUGHT_LONG",
                           "IMPORTANT_CONVERSATION",
                           "CONFIDENTIAL",
                           "PROJECT_IDEA",
                           ])

# How many track mark to jump over when encoutering one of the patterns
PatternSkips = {"IMPORTANT_THOUGHT": 1,
                "IMPORTANT_THOUGHT_LONG": 2,
                "IMPORTANT_CONVERSATION": 4,
                "CONFIDENTIAL": 5,
                "PROJECT_IDEA": 5,
                }

PatternTime = {"IMPORTANT_THOUGHT": 60,
               "IMPORTANT_THOUGHT_LONG": 120,
               "PROJECT_IDEA": 300,
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
        if track_mark_counter <= 4:
            if reset:
                reset = False
            else:
                total_time += track_mark_interval_to_seconds(track_marks[index-1], track_marks[index])
            index += 1

        # If we have reached the longest possible pattern
        if track_mark_counter >= max(pattern.value for pattern in Pattern):
            windows.append(Pattern(track_mark_counter))
            # Depending on the amount of track markers detected in a row,
            # the next track marker may get skipped since it belongs to this group
            # if track_mark_counter in [Pattern.CONFIDENTIAL, Pattern.IMPORTANT_CONVERSATION]:
            #     index += 1
            track_mark_counter = 0
            total_time = 0
            reset = True
        # Exceeded the maximum time interval, so we reached the next pattern or this is a CONVERSATION/CONFIDENTIAL
        elif total_time > interval:
            # Move the index back once if this is part of a new group of track markers
            if track_mark_counter not in [Pattern.CONFIDENTIAL.value, Pattern.IMPORTANT_CONVERSATION.value]:
                index -= 1
            windows.append(Pattern(track_mark_counter))
            # Depending on the amount of track markers detected in a row,
            # the next track marker may get skipped since it belongs to this group
            # if track_mark_counter in [Pattern.CONFIDENTIAL, Pattern.IMPORTANT_CONVERSATION]:
            #     index += 1
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
    for window in windows:
        # Avoid saving a part that overlaps with the previous segments
        minimum = track_mark_to_seconds(track_marks[index-1]) if index > 0 else 0

        if window == Pattern.IMPORTANT_THOUGHT or window == Pattern.IMPORTANT_THOUGHT_LONG or window == Pattern.PROJECT_IDEA:
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
        mp3_track_pair_path = tqdm(zip(record.mp3_files, record.tmk_files))
    # Create the output file
    total_time = 0
    first_file = True
    with open(output_path, "w", encoding="utf-8-sig") as output_file:
        for mp3_file_path, track_markers_path in mp3_track_pair_path:
            # If placeholder file, skip but add mp3 time to total time (for mp3 with no track marker associated with them)
            if track_markers_path.name != "placeholder.tmk":
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
            if first_file:
                first_file = False
            # Get the track lenght of the mp3 file and add it to the total time
            track_length = eyed3.load(mp3_file_path).info.time_secs
            total_time += track_length

    if verbose > 0:
        print("Track marker files concatenated.")

def insert_placeholder_files(record):
    """This function inserts placeholder files in the record so that, when it comes time to concatenate them, the program knows that some mp3 have no
       track marker associated with them and then know how to merge the tmk file while keeping a correct track of time."""
    new_tmk_path_list = []
    placeholder_path = record.mp3_files[0].parent.joinpath("placeholder.tmk")
    index = 0
    for tmk_file_path in record.tmk_files:
        tmk_start_time = tmk_file_path.stat().st_birthtime
        for mp3_file_path in record.mp3_files[index:]:
            track_length = eyed3.load(mp3_file_path).info.time_secs
            mp3_start_time = mp3_file_path.stat().st_birthtime
            index += 1
            if mp3_start_time + track_length < tmk_start_time:
                new_tmk_path_list.append(placeholder_path)
                continue
            else:
                new_tmk_path_list.append(tmk_file_path)
                break

    new_record = SegmentedRecord(record_name=record.record_name, mp3_files=record.mp3_files, tmk_files=new_tmk_path_list)
    return new_record


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
        # Sort the files, even if there is only one recording
        # (have to do it here to avoid having the name section in both branch)
        record.mp3_files.sort(key=lambda x: x.name)
        record.tmk_files.sort(key=lambda x: x.name)
        # Insert placeholder tmk files if some mp3 have no track marker associated with them
        record = insert_placeholder_files(record)
        # Get first mp3 creation date and time using pathlib
        first_mp3_creation_time = record.mp3_files[0].stat().st_birthtime
        creation_time_datetime = datetime.fromtimestamp(first_mp3_creation_time)
        datetime_formatted = creation_time_datetime.strftime("%Y-%m-%d@%Hh%Mm%Ss")
        # New record name
        new_mp3_path = path.joinpath(datetime_formatted + "_merged" + ".mp3")
        new_tmk_path = path.joinpath(datetime_formatted + "_merged" + ".tmk")
        # Check if it is segmented or not
        if len(record.mp3_files) > 1:
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
            if len(record.tmk_files) > 0:
                record.tmk_files[0].rename(new_tmk_path)
            else:
                new_tmk_path = path.joinpath("EMPTY.tmk")
        # Add the new recording to the list
        final_records.append(Record(record_name=record.record_name,
                                    mp3_file=new_mp3_path,
                                    tmk_file=new_tmk_path))

    return final_records

def split_audio_based_on_track_marks_pattern(record):
    """Splits the mp3 file into segments based on track marker pattern"""
    # Get the track marks pattern (check if they are any first)
    if record.tmk_file.name == "EMPTY.tmk":
        return
    track_marks = read_track_markers(record.tmk_file)
    track_marks_patterns = find_track_mark_patterns(track_marks)
    # Split the mp3 file into segments
    split_audio_file_into_segments(record, track_marks_patterns)

def split_audio_file_into_segments(record, track_marks_patterns):
    """Splits the mp3 file into segments based on track marker pattern"""
    # Split the mp3 file into segments
    index_of_types = {pattern: 0 for pattern in list(Pattern)}
    #index_of_types = {Pattern.IMPORTANT_THOUGHT: 0, Pattern.IMPORTANT_THOUGHT_LONG: 0, Pattern.IMPORTANT_CONVERSATION: 0}
    for track_marks_pattern in track_marks_patterns:
        segment_type = track_marks_pattern.type
        if segment_type == Pattern.CONFIDENTIAL:
            continue
        index_of_types[segment_type] += 1
        timestamps = [track_mark_to_ffmpeg_timestamps(track_mark_seconds) for track_mark_seconds in track_marks_pattern[0:2]]
        # Create datetime formated name for the segment based on when that segment happened
        mp3_timestamp = datetime.strptime(record.mp3_file.name.split("_")[0], "%Y-%m-%d@%Hh%Mm%Ss").timestamp()
        segment_timestamp = mp3_timestamp + track_marks_pattern[0]
        segment_datetime = datetime.fromtimestamp(segment_timestamp)
        # String representing the date of the recording of the segment
        recording_date_formatted = segment_datetime.strftime("%Y-%m-%d")
        # String representing the date and time at which the segment starts
        segment_datetime_formatted = segment_datetime.strftime("%Y-%m-%d@%Hh%Mm%Ss")
        segment_filename = segment_datetime_formatted + "_" + segment_type.name + "_" + str(index_of_types[segment_type]) + ".mp3"
        output_file_name = record.mp3_file.parent.joinpath(segment_type.name).joinpath(recording_date_formatted).joinpath(segment_filename)

        # Create output directory if it doesn't exist
        output_file_name.parent.mkdir(parents=True, exist_ok=True)
        # Create the new MP3 segment file
        subprocess.run(["ffmpeg", "-i", record.mp3_file.resolve(), "-ss",
                         timestamps[0], "-to", timestamps[1], "-acodec", "copy", output_file_name.resolve()],
                         stdout=subprocess.DEVNULL, check=True)

def track_mark_to_ffmpeg_timestamps(track_mark_seconds):
    """Converts a track marker to ffmpeg timestamps"""
    hours = int(track_mark_seconds // 3600)
    minutes = int((track_mark_seconds % 3600) // 60)
    seconds = int(track_mark_seconds % 60)
    return f"{hours}:{minutes}:{seconds}"

if __name__ == '__main__':
    # Get all recordings in the folder
    recordings = search_and_combine_recordings(Path(r'/Users/zach-mcc/MP3 Journal'))
    for recording in recordings:
        # Split all of them into segments
        split_audio_based_on_track_marks_pattern(recording)
        # Delete the merged mp3 file
        recording.mp3_file.unlink(missing_ok=True)
        recording.tmk_file.unlink(missing_ok=True)

    print("Operation completed!")
