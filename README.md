# MSVC headers downloader

Downloads and extracts MSVC headers directly from Microsoft's servers (the same
way the Visual Studio installer does it).

This can be useful when cross-compiling for Windows from Linux using clang-cl.

Note that the headers need to be stored on a case-insensitive file system, since casing in `#include` directives is not internally consistent.

```
usage: msvc_headers_downloader.py [-h] [--channel CHANNEL] output-dir

positional arguments:
  output-dir

options:
  -h, --help         show this help message and exit
  --channel CHANNEL  url to the release channel to use (default: https://aka.ms/vs/16/release/channel)
```

# Dependencies

- Python
- Python [requests](https://pypi.org/project/requests/)
- libmsi from [msitools](https://gitlab.gnome.org/GNOME/msitools)

# Missing features

- Release channel listing and selection
- Custom package selection
- Package version selection (currently, the latest version is always used)
- Signature verification
