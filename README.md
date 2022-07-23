# MP3Journaling
This app is meant to be used in conjunction with a SONY TX660. The intention is to be able to record your entire day in a single MP3 file and leave track marks where you had an idea and said it out loud or had a very intersting conversation with someone and want to keep a record of it without having to stop, take out your digital recorder and repeat the idea again or list the important point of a conversation out loud. It is meant to be a discreet way to journal without interruption to your daily life. In effect, it will split an MP3 file in the following way based on track marks left in it using the TX660:

1. If a single track mark is present (no other track mark around it in a range of -15/+15 seconds) it will take the last X minute of recording and make a new MP3 file with it (the name of the MP3 file represents the time of the day of the recording in the format FROM_XXhYY-TO_XXhYY.mp3. Take note that the time of your TX660 must be set properly for this naming to be right).
2. If two track marks are present in succession (still -15/+15 second range) it will take the last Y minutes of recording and make a new MP3 file with it.
3. If three track mark are present in succession (still -15/+15 second range) it will take all that is in between these three track marks and the next track mark (no matter how far forward it is in the recording) and make an MP3 file with that.
4. If four track marks are present in succession (still -15/+15 second range) it will take all that is in between these four track marks and the next track mark (no matter how far forward it is in the recording) and mark it has data that must be deleted. In doing so, if you find yourself putting a single or double track mark that would record some of that data due to the lenght of the recording overlapping with this section, it will remove it from that journaling section (making that section shorter than X or Y minutes but preventing possibly confidential or innapropriate data from being saved along with it). This case is espacially usefull for private meeting or simply stuff you think and know in advance should't be recorded in any way shape or form but don't want to stop your recording for (since the point of this is to be able to record your whole day without having to interact manually with the file at the end).