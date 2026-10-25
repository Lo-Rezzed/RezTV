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
3. Pick a folder from the **Folder** list (it remembers the one you used last; **Unsorted** is the default). To start a new folder, choose **New folder...** and type its name, or click **Create folder** to make an empty folder now and fill it later
4. Click **Upload**. If any of the files are already in that folder (same file name, ignoring upper/lower case), RezTV lists them first and asks: **Skip duplicates**, **Upload anyway** or **Cancel**. Each file then shows its upload progress
5. When all files are done, an **upload summary** table lists each file with its media ID, folder, result (uploaded, skipped or the error) and a **spec note**: whether the video already matches the station format or will be converted (and why, e.g. "frame rate 29.970 (station 30)"). Click **Copy as CSV** to paste the table into a spreadsheet or a note
6. After uploading, the video appears in the Media Library under its folder with the status **pending**, then **converting**
7. RezTV converts it to the station format (see [Preparing videos](preparing-videos.md)). The list refreshes itself, and when the status reads **ready** the video shows its length and can be added to a channel
8. Audio files are marked **♫ audio** in the Media Library. They are converted to AAC, 44.1 kHz stereo, with the volume evened out, and can only be added to the audio playlist of a channel in **Separate audio** mode
9. If the status reads **failed**, the reason is shown under the video. Click **Retry**, or delete it and upload a different copy

## Export settings

RezTV converts anything you upload, but files that already match the station
format go on air faster and look better, because they are only copied, not
re-encoded. For clips you make yourself (for example in iMovie), export them like
this:

| Setting | Use | Not |
|---|---|---|
| Frame rate | **30 fps, constant** | 29.97 fps, 60 fps, or "variable"/"automatic" |
| Video codec | **H.264** | HEVC/H.265, ProRes |
| Pixel format | **yuv420p** (8-bit 4:2:0) | 10-bit, 4:2:2, 4:4:4 |
| Size | **1280x720** (the size this station is set to in `STATION_RESOLUTION`; match yours if it differs) | other sizes are re-encoded and letterboxed to fit |
| Loops | **exactly 8 seconds** (240 frames at 30 fps) | 7.99 s or 8.01 s |
| Sound | AAC stereo 44.1 kHz, or none (a silent track is added) | |

**Why constant 30 and not 29.97?** The station plays at exactly 30 frames per
second. A 29.97 fps clip (what many editors, including iMovie, export by default)
or a variable-frame-rate clip is re-encoded on upload, and to get from 29.97 to 30
a frame is repeated now and then. In a short loop that can show as a small hitch.
RezTV only skips the re-encode when the clip's nominal and average frame rates are
both exactly 30/1, and codec, pixel format and size match too. The upload summary
tells you which files were converted and why.

**iMovie exports: use Shutter Encoder.** iMovie exports often come out at
29.97 fps or with a variable frame rate, which RezTV then re-encodes. The tested
route is to export from iMovie at the best quality, then
convert the file with [Shutter Encoder](https://www.shutterencoder.com) (free, Mac
and Windows):

1. Drop the iMovie export into Shutter Encoder and choose the **H.264** function.
2. Set the resolution to **1280x720**.
3. Under **Advanced features**, tick **Conform by**, set the frame rate to **30**
   and pick a mode. For an 8 second loop exported at 29.97, **Speed** keeps every
   frame and plays them 0.1% faster, so the loop stays seamless and lasts exactly
   8.000 s. **Blending** keeps the original length instead.
4. Keep the colour format at 8-bit 4:2:0 (yuv420p; don't pick a 10-bit or 4:2:2
   option), then click **Start function**.

Menu names can differ slightly between Shutter Encoder versions. To check a
finished file before uploading (if you have ffmpeg installed):

```bash
ffprobe -v error -select_streams v:0 \
  -show_entries stream=codec_name,pix_fmt,width,height,r_frame_rate,avg_frame_rate,nb_frames \
  -of default=nw=1 loop.mp4
```

You want `codec_name=h264`, `pix_fmt=yuv420p`, `width=1280`, `height=720`,
`r_frame_rate=30/1`, `avg_frame_rate=30/1` and, for an 8 second loop,
`nb_frames=240`. See also [Preparing videos](preparing-videos.md).

## Media Folders

- The **Folders** list on the left of the Media Library shows every folder and how many videos it holds. Click one to see only those videos, or **All media** to see everything
- **Create folder** (in the upload section) makes an empty folder straight away, so you can set up folders before uploading. An empty folder is kept as an empty directory on the server and shows with (0) items
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

## On-screen media ID and song title

On channels that play music separately from the picture (separate audio mode, and
the filler blocks of mixed mode), RezTV draws two small captions on the video: the
media ID of the clip on screen in the bottom left, and the title of the song
playing in the bottom right. Programs in mixed mode (videos with their own sound)
show nothing.

- Turn it on or off per channel with the **On-screen ID & song** checkbox in the
  channel's box. It is on for every channel by default.
- Mixed channels pick up the change at the next filler block; separate-audio
  channels restart right away.
- The song title is the track's title in the library (the file name, without the
  extension). Rename a track to change what is shown.
- The captions follow the durations stored in the library, so they stay in step
  with what plays. `OVERLAY_OPACITY` (default 0.6) and `OVERLAY_FONT` in `.env`
  change the look.

## Media library: folders, pages, search and sorting

The library shows one collapsible group per folder. Click a folder's name to open
or close it; the page remembers which folders you left open. Each folder shows one
page of items at a time, with Prev/Next buttons. Clicking a folder in the sidebar
shows only that folder, already open, with the "Add folder to channel" bar.

Above the library:

- **Search file names**: type part of a file name (or title). Results show as one
  list across all folders, each with the folder it is in. If a folder is picked in
  the sidebar, only that folder is searched; click **All media** to search
  everything. Upper/lower case does not matter. Clear the box to go back to the
  folder view.
- **Sort**: **Newest first** (the default, most recent uploads at the top) or
  **Oldest first**.
- **Show 25 / 50 / 100 per page**.

The page remembers your sort and page size in this browser.

## Uploading several files

In **Upload Video or Audio**, select several files at once (Ctrl/Cmd- or
Shift-click in the file picker). They all go to the folder you type (optional) and
upload one after another, each with its own line showing progress and the result
(ID or error). A failed file does not stop the rest. Duplicates are checked before
anything is sent, and the summary table at the end covers the whole batch,
including skipped duplicates (see [Uploading Videos and Music](#uploading-videos-and-music)).

## Station backup and restore

A backup is one `.tar.gz` file in the backups folder (`./backups` next to
`docker-compose.yml`; `/app/backups` in the container). It holds:

- `database.json`: every channel, playlist, audio playlist, setting and media entry.
- `media/`: every media file (optional; leave it out for a small, quick backup).

**Back up now** starts a backup right away. It runs in the background on the
server: the page shows progress (media files and bytes written) and, when it is
done, the new file's name, and the list refreshes. You can leave or reload the
page; it picks up a backup that is still running. With media included this can
take a while and needs free disk space about the size of your media folder.

Only one backup or restore runs at a time. Starting another while one is running
says so ("A backup or restore is already running") instead of queueing it. If
something between your browser and the station (such as nginx) answers with an
error page instead of RezTV, the page shows its HTTP status (for example
"HTTP 504 Gateway Timeout") rather than a bare "failed".

**Download** next to a backup saves a copy to your computer (you need to be
logged in to the admin page). This is the easiest way to keep a copy off the
server.

**Scheduled backups**: set *every N hours* (0 turns it off), how many to keep, and
whether to include media, then **Save Schedule**. The station checks once a minute
and makes a backup when the newest scheduled one is older than N hours. Only
scheduled backups are deleted when there are more than the number to keep; manual
backups stay until you delete them.

**Restore** replaces the whole station with the backup's copy: channels,
playlists, settings and the media list, plus the media files if the backup has
them. You confirm twice (a warning, then typing the backup's name). Before
restoring, RezTV saves the current database as a `-pre-restore` backup (no media),
so a restore can be undone by restoring that file. All streams stop for a moment;
channels that were on air in the backup start again. Note that the backup schedule
itself is part of the settings and is restored too.

Files in the media folder that are not in the backup are left in place (they are
just not listed in the library anymore). To move a station to a new server, copy
a backup file into the new server's `backups` folder and restore it there.

Keep copies of important backups off the server too (use **Download**, or `scp` /
`rsync` from the `backups` folder), since a backup on the same disk does not help
if that disk fails.

**Restore still runs while you wait.** Unlike Back up now, a restore keeps the
browser request open until it finishes, and restoring a backup with media can take
minutes. If RezTV is behind nginx, make sure `proxy_read_timeout` is long enough
(the [domain and SSL guide](domain-ssl.md) uses `600s`; raise it for very large
media folders). nginx's default is 60 seconds: with that, the page reports
"HTTP 504" after a minute while the restore carries on on the server. Wait a few
minutes and reload the page before trying anything else.
