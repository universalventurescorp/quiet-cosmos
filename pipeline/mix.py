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


# "documentary_max" (18-oct-2026): Luis's voice E at the highest volume that does not distort: the documentary chain
# plus a two-stage compressor (dense, steady voice); pair with mix.lufs -10.5 and voice.quiet_breaths
VOICE_EQ["documentary_max"] = (VOICE_EQ["documentary"]
                               + ",acompressor=threshold=-30dB:ratio=5:attack=5:release=150:makeup=4,"
                               "acompressor=threshold=-14dB:ratio=3:attack=3:release=100")

# "clara" (18-oct-2026): Luis's favourite take (E, by paragraphs) sounded a bit low and dull; same warm documentary
# chain plus less boxiness (350 Hz), presence (2.5 kHz) and air (6 kHz)
VOICE_EQ["clara"] = VOICE_EQ["documentary"].replace(
    ",deesser", ",equalizer=f=350:t=q:w=0.8:g=-3,equalizer=f=2500:t=q:w=1.0:g=3,highshelf=f=6000:g=2,deesser", 1)


def mix(narration, music, out, total, music_volume=0.16, lufs=-16, fade_out=6.0, duck=True, voice_eq="clean",
        voice_pitch_st=0.0, voice_size_st=0.0, sfx=None, sfx_volume=1.0):
    """sfx: optional sound-design track (pipeline/sfx.py), same length as the episode; it joins the music bus,
    so it ducks under the narrator together with the score."""
    try:
        return _mix(narration, music, out, total, music_volume, lufs, fade_out, duck, voice_eq, voice_pitch_st,
                    voice_size_st, sfx, sfx_volume)
    except Exception:
        if not (voice_pitch_st or voice_size_st):
            raise
        print("   voice pitch/size change failed (no rubberband in ffmpeg?): mixing without it")
        return _mix(narration, music, out, total, music_volume, lufs, fade_out, duck, voice_eq, 0.0, 0.0,
                    sfx, sfx_volume)


def _measure_lufs(path):
    import subprocess
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "ebur128", "-f", "null", "-"],
                       capture_output=True, text=True)
    vals = [l.split()[1] for l in r.stderr.splitlines() if l.strip().startswith("I:")]
    return float(vals[-1]) if vals else None


def _mix(narration, music, out, total, music_volume, lufs, fade_out, duck, voice_eq, voice_pitch_st, voice_size_st,
         sfx=None, sfx_volume=1.0):
    # loudnorm cannot push a mix above ~-13 LUFS (it backs off to protect peaks): for "loud" targets the mix is
    # rendered plain, measured, then raised with a gain + limiter (two passes)
    loud = lufs > -13
    final = "anull" if loud else f"loudnorm=I={lufs}:TP=-1.5:LRA=11"
    if loud:
        import pathlib
        final_out = pathlib.Path(out)
        out = str(final_out.with_name(final_out.stem + "_premaster.wav"))
    voice = VOICE_EQ.get(voice_eq, VOICE_EQ["clean"]) + ",aformat=channel_layouts=stereo"
    if voice_size_st:
        # "bigger" voice (18-oct, Luis: like an older adult, more voice): resonances (formants) lowered by
        # voice_size_st semitones with the pitch unchanged, plus a little chest and density
        d, u = 2 ** (-voice_size_st / 12), 2 ** (voice_size_st / 12)
        voice = (f"rubberband=pitch={d:.5f}:formant=shifted:pitchq=quality,"
                 f"rubberband=pitch={u:.5f}:formant=preserved:pitchq=quality,"
                 + voice + ",equalizer=f=140:t=q:w=0.8:g=2.5,"
                 "acompressor=threshold=-22dB:ratio=2:attack=15:release=250:makeup=1")
    if voice_pitch_st:
        # whole narration a little higher (formants kept, so it is the same man, not a chipmunk)
        voice = (f"rubberband=pitch={2 ** (voice_pitch_st / 12):.5f}:formant=preserved:pitchq=quality,"
                 + voice)
    # music bus = score (+ sound design)
    score = f"[1:a]aresample=48000,aformat=channel_layouts=stereo,volume={music_volume},afade=t=in:d={5 if duck else 1}"
    if sfx:
        bus = (f"{score}[m0];[2:a]aresample=48000,aformat=channel_layouts=stereo,volume={sfx_volume}[fx];"
               f"[m0][fx]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[m];")
    else:
        bus = f"{score}[m];"
    if duck:
        graph = (f"[0:a]{voice},asplit=2[v][sc];" + bus +
                 f"[m][sc]sidechaincompress=threshold=0.04:ratio=3:attack=400:release=2500:makeup=1[md];"
                 f"[v][md]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
                 f"afade=t=out:st={max(0, total - fade_out):.3f}:d={fade_out},"
                 f"{final},aresample=48000[a]")
    else:
        graph = (f"[0:a]{voice}[v];" + bus +
                 f"[v][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
                 f"afade=t=out:st={max(0, total - fade_out):.3f}:d={fade_out},"
                 f"{final},aresample=48000[a]")
    run(["ffmpeg", "-y", "-loglevel", "error",
         "-i", narration, "-stream_loop", "-1", "-i", music] + (["-i", str(sfx)] if sfx else []) + [
         "-filter_complex", graph, "-map", "[a]", "-t", f"{total:.3f}",
         "-c:a", "pcm_s16le", out])
    if loud:
        have = _measure_lufs(out)
        gain = (lufs - have) if have is not None else 0.0
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", out, "-af",
             f"volume={gain:.2f}dB,alimiter=limit=0.89:attack=3:release=60:level=false,aresample=48000",
             "-c:a", "pcm_s16le", final_out])
        print(f"   master: {have} LUFS -> {_measure_lufs(final_out)} LUFS")
        return final_out
    return out
