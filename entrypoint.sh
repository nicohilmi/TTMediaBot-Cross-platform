#!/bin/bash
set -e

# Audio no longer needs a sound server: FFmpeg decodes the media and the bot
# hands the PCM straight to TeamTalk (virtual sound device).
exec "$@"
