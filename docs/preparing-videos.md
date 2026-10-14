# Preparing Videos for RezTV

RezTV converts every upload for you, so in most cases you can upload files as they are.

## What you can upload

- **Video:** MP4, MOV, MKV and WebM
- **Animated GIF:** converted to a video and looped (see below)
- **Audio (for Separate audio channels):** MP3, M4A, AAC, FLAC, WAV and OGG
- **Size:** up to 2 GB per file by default (`MAX_UPLOAD_MB` in `.env`)

Every upload is checked with ffprobe first. A file that isn't a readable video (or, for audio files, has no readable sound) is rejected straight away.

## What RezTV does after upload

Once the upload finishes, RezTV converts the file in the background to the station format:

| Setting | Default | Change in `.env` |
|---|---|---|
| Size | 1920x1080. Other sizes are scaled to fit and letterboxed with black bars, never stretched or cropped | `STATION_RESOLUTION` |
| Frame rate | 30 fps, constant | `STATION_FPS` |
| Video | H.264, yuv420p | |
| Audio | AAC stereo, 44.1 kHz, 128 kbps | |
| Volume | Evened out to -16 LUFS so videos play at a similar loudness | `STATION_LOUDNORM`, `STATION_LOUDNORM_TARGET` |
| Silent clips | A silent audio track is added, so the channel's sound never drops out | |
| GIFs | Looped until they last at least 30 seconds | `GIF_MIN_SECONDS` |

**Already in the station format? No re-encode.** If an upload is already an MP4 (or MOV) with H.264 yuv420p video at exactly the station size and frame rate (within 0.05 fps) and one AAC stereo 44.1 kHz audio track, RezTV only copies it into a fresh MP4 with fast-start (a few seconds, no quality loss) instead of re-encoding it. Volume is not evened out on this path, so normalize finished programs before you export them. The server log says which path each upload took ("already matches station format; remuxing only" or "converting audio only" or "needs re-encode: <reason>"). If only the sound is off (for example 48 kHz instead of 44.1 kHz, or no audio track), the picture is copied as is and just the sound is converted and evened out, which takes seconds to a minute instead of a full re-encode. Set `CONVERT_SKIP_MATCHING=false` to always re-encode.

Audio files are converted to AAC stereo, 44.1 kHz, 192 kbps, evened out to the same loudness target (`STATION_LOUDNORM`), with cover art and tags removed. They are stored as `.mka` files next to the videos. Conversion is fast: a few seconds per song.

The Media Library shows each file's status:

- **pending:** waiting its turn (one file is converted at a time)
- **converting:** being converted now
- **ready:** done. Only ready videos can be added to a channel or played
- **failed:** couldn't be converted. Hover over the status or read the red message under it, then click **Retry** or delete the video

Conversion takes roughly as long as the video plays on a small server, and less on a faster one. After a restart, anything that was waiting or converting starts again on its own.

By default the original upload is deleted once conversion succeeds, to save disk space. Set `KEEP_ORIGINALS=true` in `.env` to keep it next to the converted file.

Changing the station settings only affects new uploads. Keep the same settings for the life of a station so every video matches.

## Tips

- Upload the best-quality copy you have. RezTV re-encodes it once, so starting from a sharp file gives a sharp result.
- Videos uploaded before automatic conversion existed are marked ready and play as before. If one of them causes trouble on a channel, delete it and upload it again so it gets converted.
- Very long files take a while to convert. Test with a short clip first.
