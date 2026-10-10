# Preparing Videos for RezTV

For the best and most reliable playback, prepare your video files before uploading.

## Recommended Settings

- **Container**: MP4
- **Video Codec**: H.264 (AVC)
- **Audio Codec**: AAC
- **Frame Rate**: Keep it consistent across all videos (24, 25, or 30 fps)
- **Resolution**: 1280x720 (720p) or 1920x1080 (1080p)
- **Pixel Format**: yuv420p

## Why consistent frame rate is important

RezTV plays videos one after another in a continuous loop.  
Mixing different frame rates (for example 24 fps and 29.97 fps) can cause freezes or stuttering when switching between videos.

## Simple conversion with FFmpeg

If you have FFmpeg installed, you can convert a video like this:

```bash
ffmpeg -i input.mp4 -vf fps=30 -c:v libx264 -preset fast -crf 20 -c:a aac -b:a 128k output.mp4
You can also use free tools such as Shutter Encoder or HandBrake if you prefer a graphical interface.

Tips
Use the same resolution and frame rate for all videos in a channel when possible
Avoid very high bitrates unless necessary
Test a short video first after uploading
