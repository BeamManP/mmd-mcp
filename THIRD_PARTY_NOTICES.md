# License scope and third-party components

The project-authored source code, documentation, scripts, and authoring skill are
licensed under MIT No Attribution (MIT-0); see [LICENSE](LICENSE). Attribution,
publication of modifications, and use of the same license for downstream code
are not required by that license. The copyright line identifies the project's
contributors collectively; it does not assign ownership to a new entity.

MIT-0 does not relicense third-party code or assets. The following notices
describe the current distribution, not a grant of additional third-party rights.

## Microsoft runtime in the native bridge

`mmd_mcp/_native/mmd_selection.dll` is built from this project's
`native/selection_bridge.cpp` using the MSVC release static runtime (`/MT`).
The project's C++ source is MIT-0. Microsoft runtime portions incorporated by
the toolchain remain subject to the applicable Microsoft license terms.

`LicenseRef-Microsoft-Runtime` in the package license expression identifies
those Microsoft runtime terms, not a project-authored license. The combined
expression applies to the package containing the compiled DLL; it does not
add Microsoft terms to the project's independently reusable source code.

The checked local toolchain is Visual Studio Community 2022. Its license permits
individual development of one's own applications, including applications for
sale. Distributable-code provisions include adding substantial application
functionality and requiring downstream terms that protect the Microsoft code.
Refer to the actual terms for all conditions:

- [Visual Studio Community 2022 license terms](https://visualstudio.microsoft.com/license-terms/vs2022-ga-community/)
- [Visual Studio 2022 redistribution list](https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution)
- [Visual C++ redistribution guidance](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files?view=msvc-170)

The inspected linker map identifies `LIBCMT`, `libvcruntime`, and `libucrt`.
The Windows SDK redistribution list explicitly covers the SDK's static UCRT
library when linked into a program. The Visual Studio 2022 redistribution list
does not directly list the two MSVC static libraries, so their applicable grant
and the required downstream terms still need to be resolved before publishing
the binary wheel. This is an unresolved verification point, not a conclusion
that static linking is prohibited.
This notice alone does not complete that verification. Rebuilding with another
toolchain requires checking that toolchain's terms as well.

## Separately installed Python dependencies

The mmd-mcp wheel declares these dependencies; it does not bundle their packages.
They are installed separately by pip and retain their own license files.
Versions below are the inspected environment, not a promise about every version
allowed by `pyproject.toml`.

| Direct dependency | Inspected version | Package-declared license |
| --- | --- | --- |
| mcp | 1.29.1 | MIT |
| windows-capture | 2.0.1 | MIT |
| psutil | 7.2.2 | BSD-3-Clause |
| pywin32 | 312 | PSF |
| opencv-python | 5.0.0.93 | Apache 2.0 |

Package metadata alone is not an exhaustive account of bundled components.
In particular, the installed OpenCV third-party notice identifies FFmpeg under
LGPL-2.1. Transitive dependencies include certifi (MPL-2.0), cryptography
(Apache-2.0 OR BSD-3-Clause), and NumPy with separate bundled-library notices.

- [OpenCV third-party notices](https://github.com/opencv/opencv-python/blob/4.x/LICENSE-3RD-PARTY.txt)
- [MPL-2.0 FAQ, including file-level obligations](https://www.mozilla.org/en-US/MPL/2.0/FAQ/)

If redistributing dependencies, an offline installer, or a frozen application,
review the exact included versions and preserve required license/copyright
notices, source availability, and replacement/relinking rights as applicable.
This dependency summary is not a substitute for their license texts.

## MMD and production assets

MMD, MME, third-party models, effects, music, motions, and user production assets
are not included in the mmd-mcp wheel. Their use and redistribution remain
subject to their respective permissions. The project's MIT-0 license grants no
rights over those works.
