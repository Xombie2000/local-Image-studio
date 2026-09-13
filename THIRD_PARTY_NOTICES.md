# Third-party notices

Local Image Studio source code is released under the repository's [MIT License](LICENSE). That license does not replace the licenses or terms of its dependencies, external services, or model weights.

No model weights are distributed in this repository. Users are responsible for reviewing the current upstream terms before downloading or using a model, especially for commercial or production use.

| Component | Role | Upstream license or terms |
| --- | --- | --- |
| [MFLUX](https://github.com/filipstrand/mflux) | Local image inference | MIT |
| [MLX](https://github.com/ml-explore/mlx/blob/main/LICENSE) | Apple Silicon array and ML framework | MIT |
| [FLUX.2 Klein 4B](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B/blob/main/LICENSE.md) | Generation model weights | Apache License 2.0 |
| [FLUX.2 Klein 9B](https://huggingface.co/black-forest-labs/FLUX.2-klein-9B/blob/main/LICENSE.md) | Generation model weights | FLUX Non-Commercial License v2.1 |
| [Krea 2 Turbo](https://huggingface.co/krea/Krea-2-Turbo) | Generation model weights | Krea 2 Community License and Acceptable Use Policy; gated access |
| [SeedVR2](https://huggingface.co/numz/SeedVR2_comfyUI) | Upscaling model files | Apache License 2.0 as identified by the upstream model repository |
| User-selected LM Studio or oMLX models | Optional prompt enhancement | The license supplied by each selected model's publisher |

The FLUX.2 Klein 9B and Krea 2 Turbo terms are not equivalent to this repository's MIT license. Do not assume that availability in the app permits commercial use, production deployment, redistribution, or every category of generated content.

## MFLUX-derived compatibility files

Local Image Studio includes modified compatibility copies of portions of MFLUX under `docs/patches/mflux-seedvr2-compat/`. Those portions remain subject to the following upstream license.

MIT License

Copyright (c) 2026 Filip Strand

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
