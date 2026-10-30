#!/usr/bin/env bash
# Long journeys: move an episode's work folder between the stages of largo.yml.
#   work.sh pack     big WAVs in outputs/*/ -> FLAC (an artifact of 2-6 GB of WAV would be slow to move)
#   work.sh unpack   FLAC -> WAV again, so the pipeline finds exactly the files it left
set -euo pipefail
case "${1:-}" in
  pack)
    for w in outputs/*/*.wav; do
      [ -f "$w" ] || continue
      [ "$(stat -c %s "$w")" -gt 50000000 ] || continue
      ffmpeg -y -loglevel error -i "$w" -c:a flac "${w%.wav}.flac" && rm "$w"
      echo "packed $w"
    done ;;
  unpack)
    for f in outputs/*/*.flac; do
      [ -f "$f" ] || continue
      ffmpeg -y -loglevel error -i "$f" -c:a pcm_s16le "${f%.flac}.wav" && rm "$f"
      echo "unpacked $f"
    done ;;
  *) echo "usage: work.sh pack|unpack"; exit 1 ;;
esac
