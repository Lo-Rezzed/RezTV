# RezTV User Guide

## First Login

1. Open your admin panel: `https://yourdomain.com/admin`
2. You will be asked for a username and password (the `ADMIN_USERNAME` and `ADMIN_PASSWORD` you set in your `.env` file)
3. After logging in you will see the admin dashboard

## Setting Your Station Name

1. At the top of the admin page, enter your desired Station Name
2. Click **Save Station Name**
3. This name will appear on the public landing page and in the video player

## Uploading Videos and Music

1. Go to the **Upload Video or Audio** section
2. Select a video file (MP4, MOV, MKV or WebM), an animated GIF, or an audio file (MP3, M4A, AAC, FLAC, WAV or OGG), up to 2 GB
3. Optionally type a folder name (or pick an existing one). Leave it blank and the video goes in **Unsorted**
4. Click **Upload**. A progress bar will show the upload status
5. After uploading, the video appears in the Media Library under its folder with the status **pending**, then **converting**
6. RezTV converts it to the station format (see [Preparing videos](preparing-videos.md)). The list refreshes itself, and when the status reads **ready** the video shows its length and can be added to a channel
7. Audio files are marked **♫ audio** in the Media Library. They are converted to AAC, 44.1 kHz stereo, with the volume evened out, and can only be added to the audio playlist of a channel in **Separate audio** mode
8. If the status reads **failed**, the reason is shown under the video. Click **Retry**, or delete it and upload a different copy

## Media Folders

- The **Folders** list on the left of the Media Library shows every folder and how many videos it holds. Click one to see only those videos, or **All media** to see everything
- To move a video, click **Move** next to it and type the folder name. Typing a new name creates that folder
- Folder names can use letters, numbers, spaces, `-` and `_`. Anything else is removed
- New uploads are stored on the server under `media/<folder name>/`. Moving a video only changes its folder in the admin panel; the file stays where it is, so a channel that is playing it is not interrupted
- Videos uploaded before folders existed are shown in **Unsorted** and keep working

## Creating a Channel

1. Go to the **Create Channel** section
2. Enter a name for the channel
3. Choose how the channel plays sound:
   - **Standard**: each video plays with its own sound. This is how RezTV has always worked
   - **Separate audio**: the channel has two playlists, one of videos and one of music. Both loop on their own and RezTV plays them together: the videos are shown muted and the music plays over them. A song keeps playing when the video changes, and a video keeps playing when the song changes
   - **Mixed**: the channel alternates between finished programs and filler blocks: program 1, then a filler block, then program 2, then a filler block, and so on. Programs are the channel's video playlist and play with their own sound. A filler block shuffles the ready videos from one media folder (the **filler clips folder**), muted, with the channel's audio playlist playing over them, for a set time (**filler block length**, default 30 minutes). Set both when you create the channel, or later with **Filler Settings**
4. Click **Create Channel**
5. The new channel will also appear on the public landing page

### Changing a channel's mode

Click **Change Mode** on the channel. Switching to Standard keeps the audio playlist, so you can switch back later without rebuilding it. If the channel is on air it restarts in the new mode straight away. If you switch an on-air channel to Separate audio before it has any music, it stops; add music and click **Start Stream**.

Channels created before this option existed are Standard and keep working as before.

On a **Mixed** channel: with no filler folder (or no music) set, programs play back to back; with no programs, it plays filler blocks only. Changing the filler settings of an on-air Mixed channel restarts it. Viewers keep watching across each switch between a program and a filler block; the player just moves on to the next part.

### Which mode should I use?

- Use **Standard** for programs where picture and sound belong together: music videos, edited programs, anything with speech
- Use **Separate audio** for visual loops and clips with a soundtrack chosen separately. You can add or swap a clip or a song without re-editing anything. The music is not synced to the picture
- Use **Mixed** when you have a few edited programs and a pool of loose clips and music: the programs keep their exact edit and sound, and new clips dropped into the filler folder show up in the next filler block without re-editing anything

## Building the Audio Playlist (Separate audio and Mixed channels)

1. Upload music as described above and wait until it shows **ready**
2. In the Media Library, choose the channel next to a track (only Separate audio channels are listed) and click **Add**
3. Or open a folder and click **Add Folder to Channel**: on a Separate audio channel, the folder's videos go to the video playlist and its music to the audio playlist
4. In the Channels section, the **♫ Audio playlist** appears under the videos. Drag tracks to reorder them and click **Remove** to take one off. As with videos, restart the stream to apply changes
5. A Separate audio channel needs at least one ready video and one ready track to start

## Adding Videos to a Channel

Audio tracks can't be added to the video playlist, and videos can't be added to the audio playlist.

Only videos marked **ready** can be added; the dropdown and **Add** button stay greyed out until conversion finishes.

1. In the Media Library, use the dropdown next to a video
2. Select the channel you want
3. Click **Add**

To add a whole folder at once:

1. Click the folder in the **Folders** list
2. In the bar above the videos, choose a channel and click **Add Folder to Channel**
3. Every video in that folder is added to the end of the channel. Videos already in the channel, or not ready yet, are skipped. Add the rest later once they're ready

## Removing a Video from a Channel

- In the Channels section, click **Remove** next to a video
- This only takes it off that channel. It stays in the Media Library and in any other channels
- To delete a video from the server completely, use the red **Delete** button in the Media Library instead

## Reordering Videos

- In the Channels section, drag and drop videos to change the play order
- The new order is saved automatically

**Note:** a running channel keeps playing its old list. After adding, removing or reordering videos, click **Stop Stream** and then **Start Stream** to apply the changes.

## Starting a Channel

1. Find the channel in the Channels section
2. Click **Start Stream**
3. Wait a few seconds, then open the channel page or the public player

A started channel stays on until you click **Stop Stream**:

- If the stream crashes, RezTV restarts it automatically. It waits a little longer after each failure in a row (2 s, 4 s, 8 s ... up to 5 minutes) so a broken file can't overload the server.
- If the server or RezTV restarts, every channel that was on comes back on by itself.
- Click **Status & Log** under a channel to see whether it's on air, how many times it has restarted, and the last lines of its stream log. That's the first place to look when a channel goes quiet.

Each line of the log starts a run with the channel's mode and how many videos (and audio tracks) it is playing.

## Server load

A channel re-encodes its picture live, which is the main cost. A Separate audio channel uses about the same CPU as a Standard one: it reads one extra audio file and encodes the same single sound track. On a 4-core server, plan on one 1080p channel per core or so. The optional `STREAM_AUDIO_LOUDNORM=true` setting evens out music volume again live; it is off by default because music is already evened out when it is uploaded.

## Stream logs

Each channel writes its stream log to `logs/channel_<ID>.log` in the RezTV folder on the server. Logs are capped at 1 MB each (change with `STREAM_LOG_MAX_KB` in `.env`), and the two previous logs are kept as `.log.1` and `.log.2`.

## Public Pages

- Landing page: `https://yourdomain.com`
- Channel player: `https://yourdomain.com/channel/1` (replace 1 with the channel ID)

## Editing or Deleting

- You can rename a channel with the **Edit Name** button
- You can delete videos or entire channels with the red **Delete** buttons. Deleting a video removes its converted file (and the original, if kept) from the server
