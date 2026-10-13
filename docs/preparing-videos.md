# Preparing Videos for RezTV

RezTV converts every upload for you, so in most cases you can upload files as they are.

## What you can upload

- **Video:** MP4, MOV, MKV and WebM
- **Animated GIF:** converted to a video and looped (see below)
- **Size:** up to 2 GB per file by default (`MAX_UPLOAD_MB` in `.env`)

Every upload is checked with ffprobe first. A file that isn't a readable video is rejected straight away.

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

The Media Library shows each video's status:

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
