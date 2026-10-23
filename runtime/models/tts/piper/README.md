# Optional Piper TTS Voice

AX4LAB uses Piper as the default LeRobot recording cue voice engine.

The new public AX4LAB release does not bundle the voice model or its config.
The existing installer can acquire this optional voice at the operator's explicit
initiative:

- `en_US-lessac-medium`: local English neural voice for recording status cues.
- Model path from the repository root: `runtime/models/tts/piper/en_US-lessac-medium/en_US-lessac-medium.onnx`
- Config path from the repository root: `runtime/models/tts/piper/en_US-lessac-medium/en_US-lessac-medium.onnx.json`

Before downloading or using the voice, review its upstream
[model card](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/lessac/medium/MODEL_CARD)
and the linked
[Lessac dataset license](https://www.cstr.ed.ac.uk/projects/blizzard/2013/lessac_blizzard2013/license.html).
These references are not a representation that AX4LAB has cleared redistribution
or any particular use of the model. Downloaded files remain local and must not be
added to the public release without a separate licensing and publication review.

If you have determined that the terms permit your intended use, explicitly run
the installer from the repository root:

```bash
bash runtime/install/install_piper_tts.sh
```

The script installs `piper-tts` into `.venv`, downloads missing model/config files
from upstream, and verifies synthesis. The general bootstrap's `--with-piper`
option only installs the `tts` extra; it does not download a voice or synthesize
speech.

The LeRobot bridge passes the local paths to the recording subprocess through
`LEROBOT_TTS_PIPER_*` environment variables. The LeRobot conda environment does
not need to install Piper separately.
