"""Final audio: polished voice + ambient score that gently ducks under speech, loudness-normalized."""
from .common import run


VOICE_EQ = {
    # bright, clear: good for Kokoro, which is a little thin
    "clean": ("aresample=48000,highpass=f=75,"
              "equalizer=f=220:t=q:w=1.2:g=-1.5,equalizer=f=3200:t=q:w=1.5:g=1.5,"
              "acompressor=threshold=-22dB:ratio=2.5:attack=15:release=250:makeup=2"),
    # warm documentary narrator: body in the lows, soft highs (matched to the long-term spectrum of a
    # reference Spanish-language documentary narration); no reverb
    "documentary": ("aresample=48000,highpass=f=60,lowshelf=f=180:g=4,equalizer=f=500:t=q:w=1.0:g=-1.5,"
                    "equalizer=f=1600:t=q:w=1.0:g=1,highshelf=f=4000:g=-4,deesser=i=0.3,"
                    "acompressor=threshold=-24dB:ratio=3:attack=10:release=220:makeup=3"),
    # "estudio" (18-oct-2026): fitted on voiced frames against the reference documentary narrator (third-octave
    # long-term spectrum): less boxy 300-500 Hz (the "inside a box" colour), chest at ~190 Hz, a little presence and
    # air; spectral distance to the reference 2.5 -> 1.8 dB (smoothed 1.6 -> 1.0)
    "estudio": ("aresample=48000,highpass=f=80,equalizer=f=190:t=q:w=0.8:g=4,equalizer=f=350:t=q:w=0.7:g=-5,"
                "equalizer=f=1800:t=q:w=0.8:g=1.5,equalizer=f=3500:t=q:w=1:g=-2,highshelf=f=5000:g=2.5,"
                "deesser=i=0.4,acompressor=threshold=-24dB:ratio=3:attack=10:release=220:makeup=3"),
}


# "clara" (18-oct-2026): Luis's favourite take (E, by paragraphs) sounded a bit low and dull; same warm documentary
# chain plus less boxiness (350 Hz), presence (2.5 kHz) and air (6 kHz)
VOICE_EQ["clara"] = VOICE_EQ["documentary"].replace(
    ",deesser", ",equalizer=f=350:t=q:w=0.8:g=-3,equalizer=f=2500:t=q:w=1.0:g=3,highshelf=f=6000:g=2,deesser", 1)


def mix(narration, music, out, total, music_volume=0.16, lufs=-16, fade_out=6.0, duck=True, voice_eq="clean",
        voice_pitch_st=0.0):
    try:
        return _mix(narration, music, out, total, music_volume, lufs, fade_out, duck, voice_eq, voice_pitch_st)
    except Exception:
        if not voice_pitch_st:
            raise
        print("   voice pitch shift failed (no rubberband in ffmpeg?): mixing without it")
        return _mix(narration, music, out, total, music_volume, lufs, fade_out, duck, voice_eq, 0.0)


def _mix(narration, music, out, total, music_volume, lufs, fade_out, duck, voice_eq, voice_pitch_st):
    voice = VOICE_EQ.get(voice_eq, VOICE_EQ["clean"]) + ",aformat=channel_layouts=stereo"
    if voice_pitch_st:
        # whole narration a little higher (formants kept, so it is the same man, not a chipmunk)
        voice = (f"rubberband=pitch={2 ** (voice_pitch_st / 12):.5f}:formant=preserved:pitchq=quality,"
                 + voice)
    if duck:
        graph = (f"[0:a]{voice},asplit=2[v][sc];"
                 f"[1:a]aresample=48000,aformat=channel_layouts=stereo,volume={music_volume},afade=t=in:d=5[m];"
                 f"[m][sc]sidechaincompress=threshold=0.04:ratio=3:attack=400:release=2500:makeup=1[md];"
                 f"[v][md]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
                 f"afade=t=out:st={max(0, total - fade_out):.3f}:d={fade_out},"
                 f"loudnorm=I={lufs}:TP=-1.5:LRA=11,aresample=48000[a]")
    else:
        graph = (f"[0:a]{voice}[v];"
                 f"[1:a]aresample=48000,aformat=channel_layouts=stereo,volume={music_volume},afade=t=in:d=1[m];"
                 f"[v][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
                 f"afade=t=out:st={max(0, total - fade_out):.3f}:d={fade_out},"
                 f"loudnorm=I={lufs}:TP=-1.5:LRA=11,aresample=48000[a]")
    run(["ffmpeg", "-y", "-loglevel", "error",
         "-i", narration, "-stream_loop", "-1", "-i", music,
         "-filter_complex", graph, "-map", "[a]", "-t", f"{total:.3f}",
         "-c:a", "pcm_s16le", out])
    return out
