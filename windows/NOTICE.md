# Attribution

**[Читать по-русски](NOTICE.ru.md)**

This is the Windows port of Lexomorph (formerly SuperDictate Next). It contains
no code from the macOS version (all of it is written from scratch in Python +
PySide6), but it follows that version's behaviour, setting names and data
layout, so the chain of authorship is kept in full.

| Project | Author | Role |
| --- | --- | --- |
| [Parakey](https://github.com/rcourtman/Parakey) | Richard Courtman | original (macOS, Swift) |
| [SuperDictate](https://github.com/shlgd/SuperDictate) | shlgd | fork of Parakey whose behaviour was followed (later developed into Lexomorph) |
| Dictation for Windows | metawka | this port (Python, PySide6) |

All three are distributed under the MIT licence, see [LICENSE](LICENSE).

## Third-party components

| Component | Licence | Purpose |
| --- | --- | --- |
| [Parakeet TDT 0.6B v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) | CC-BY-4.0 (NVIDIA) | speech recognition model |
| [onnx-asr](https://github.com/istupakov/onnx-asr) | MIT | model loader and decoder |
| [Parakeet TDT 0.6B v3, OpenVINO](https://huggingface.co/FluidInference/parakeet-tdt-0.6b-v3-ov) (FluidInference, mirror [VoiceScribe](https://huggingface.co/VoiceScribe/voicescribe-parakeet)) | CC-BY-4.0 | NPU model |
| [GigaAM v3](https://huggingface.co/ai-sage/GigaAM-v3), OpenVINO and NPU calibration by [Andrewsab](https://huggingface.co/Andrewsab/gigaam-v3-e2e-rnnt-ov-npu) (mirror [VoiceScribe](https://huggingface.co/VoiceScribe/voicescribe-gigaam-npu)) | MIT | NPU model |
| [Horizon Labs punctuation-restoration](https://huggingface.co/Horizon-Labs/punctuation-restoration-base) (Small, Base; based on [mmBERT](https://huggingface.co/jhu-clsp/mmBERT-base), MIT) | Apache-2.0 | punctuation restoration |
| [OpenVINO](https://github.com/openvinotoolkit/openvino) | Apache-2.0 | running models on the NPU |
| [ONNX Runtime](https://onnxruntime.ai/) | MIT | running the model |
| [PySide6](https://doc.qt.io/qtforpython/) | LGPLv3 | user interface |
| [sounddevice](https://python-sounddevice.readthedocs.io/) / PortAudio | MIT | audio capture |
| [pycaw](https://github.com/AndreMiras/pycaw) | MIT | system audio ducking |

Model weights are not part of the installer: they are downloaded on first run
to `%LOCALAPPDATA%\Lexomorph\Models` and remain under NVIDIA's CC-BY-4.0
licence.
