# VPS Recommendations for RezTV

RezTV uses FFmpeg to continuously re-encode and stream your channels.  
CPU is the most important resource.

## Minimum Requirements

| Use Case                    | CPU          | RAM     | Storage     | Notes |
|----------------------------|--------------|---------|-------------|-------|
| Testing / 1 channel        | 2 cores      | 4 GB    | 40 GB SSD   | Fine for personal use |
| 1–2 channels (light)       | 4 cores      | 8 GB    | 80 GB SSD   | Recommended starting point |
| 3–5 channels               | 6–8 cores    | 16 GB   | 160 GB SSD  | Comfortable for most users |
| 6+ channels or many viewers| 8+ cores     | 32 GB+  | 250 GB+ NVMe| Consider dedicated server |

## Important Notes

- **CPU** matters most because RezTV re-encodes video in real time.
- Using the `veryfast` preset (default) keeps CPU usage reasonable.
- Higher resolution or higher frame rate videos use more CPU.
- Consistent frame rate and resolution across all videos improves performance and stability.

## Bandwidth (Viewers)

Approximate outbound bandwidth needed:

| Viewers | 720p (~2.5 Mbps) | 1080p (~4–5 Mbps) |
|---------|------------------|-------------------|
| 10      | 25 Mbps          | 50 Mbps           |
| 50      | 125 Mbps         | 250 Mbps          |
| 100     | 250 Mbps         | 500 Mbps          |
| 500     | 1.25 Gbps        | 2.5 Gbps          |

Most VPS providers offer 1 Gbps ports. For larger audiences you should use a CDN.

## Storage

- Store your original video files + generated HLS segments.
- SSD or NVMe is strongly recommended.
- Plan for at least 2–3× the size of your media library.

## Recommended Providers (examples)

Any reliable VPS provider that offers Ubuntu 22.04/24.04 and good CPU performance works.  
Look for providers with dedicated or high-frequency CPU cores rather than heavily shared ones.
