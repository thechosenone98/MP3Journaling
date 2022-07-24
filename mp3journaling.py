"""This module implements function to split an MP3 recording in multiple
   parts based on different track marker patterns."""
from pathlib import Path
from collections import namedtuple
from enum import Enum
from pprint import pprint

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
    """This functions open the TRM file linked to the MP3 and returns
       all the track marker in it in a list of timestamps"""
    with open(filename, 'r', encoding="ASCII") as track_marker_file:
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

def find_track_mark_pattern(track_marks, maxTimeInterval=30):
    """This function finds the track markers pattern in the TRM file.
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


if __name__ == '__main__':
    # Get all mp3 files in the current directory and tuple them with their according TRM file
    recordings = zip(list(Path.cwd().glob('*.mp3')), list(Path.cwd().glob('*.trm')))
    for recording in recordings:
        pprint(find_track_mark_pattern([ "[00000:01.00]",
                                     "[00000:02.00]",
                                     "[00000:03.00]",
                                     "[00000:10.00]",
                                     "[00000:11.00]",
                                     "[00000:45.00]",
                                     "[00000:47.00]",
                                     "[00002:08.00]",
                                     "[00002:09.00]",
                                     "[00002:10.00]",
                                     "[00002:11.00]",
                                     "[00002:30.00]",
                                     "[00010:30.00]",
                                     "[00012:30.00]",
                                     "[00012:31.00]",
                                     "[00012:32.00]",
                                     "[00013:30.00]",]))