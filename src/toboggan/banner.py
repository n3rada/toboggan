# toboggan/src/utils/banner.py

# Local library imports
from . import __version__ as version

def display_banner() -> str:
    return rf"""
 _____      _
/__   \___ | |__   ___   __ _  __ _  __ _ _ __
  / /\/ _ \| '_ \ / _ \ / _` |/ _` |/ _` | '_ \
 / / | (_) | |_) | (_) | (_| | (_| | (_| | | | |
 \/   \___/|_.__/ \___/ \__, |\__, |\__,_|_| |_|
                        |___/ |___/ {version}
      Slides onto remote system with ease
                 @n3rada
"""
