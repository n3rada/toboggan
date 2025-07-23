# Local library imports
from toboggan.version import get_version


def show() -> str:
    version = get_version()

    return rf"""
 _____      _
/__   \___ | |__   ___   __ _  __ _  __ _ _ __
  / /\/ _ \| '_ \ / _ \ / _` |/ _` |/ _` | '_ \
 / / | (_) | |_) | (_) | (_| | (_| | (_| | | | |
 \/   \___/|_.__/ \___/ \__, |\__, |\__,_|_| |_|
                        |___/ |___/
      Slides onto remote system with ease
                 @n3rada
                  {version}
"""
