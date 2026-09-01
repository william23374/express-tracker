"""Express package tracking — interactive terminal and CLI."""

__version__ = "1.0.0"

# Bake the build number in at package time so `ver` reports v1.0.0+build<号>.
# The packaging scripts (macos/build_installer.sh and the GitHub Actions
# Windows workflow) write src/express/_build.py right before PyInstaller runs.
# For a plain source / editable install the module is absent -> BUILD_NO = "".
try:  # pragma: no cover - present only in packaged builds
    from express._build import BUILD_NO
except ImportError:  # plain source / editable install
    BUILD_NO = ""

__version_full__ = f"{__version__}+build{BUILD_NO}" if BUILD_NO else __version__
