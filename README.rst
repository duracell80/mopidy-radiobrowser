# Mopidy-RadioBrowser

Mopidy extension for playing music from `RadioBrowser <http://www.radiobrowser.info>`_.
Listen to the world’s radio with 25,000 stations of music, sports and news streaming from every continent.

Acknowledgement and thanks to Nick Steel's `TuneIn plugin <https://github.com/kingosticks/mopidy-tunein>`_ that was based on.
This product uses RadioBrowser API but is not endorsed, certified or otherwise approved in any way by RadioBrowser.

## Installation

Install by running::

    sudo python3 setup.py install

Some radio streams may require additional audio plugins.
These can be found in the gstreamer plugin packages for your system.
See https://mopidy.com/ext/radiobrowser/ for alternative installation methods.


## Configuration
=============

Before starting Mopidy, you must add configuration for
Mopidy-RadioBrowser to your Mopidy configuration file::

    [radiobrowser]
    enabled = true
    timeout = 5000

sudo reboot

## Project resources
=================

- `Source code <https://github.com/RalfLangeDresden/mopidy-radiobrowser>`_
- `Issue tracker <https://github.com/RalfLangeDresden/mopidy-radiobrowser/issues>`_
- `Changelog <https://github.com/RalfLangeDresden/mopidy-radiobrowser/blob/master/CHANGELOG.rst>`_


Credits
=======

- Original author: `Ralf Lange <https://github.com/RalfLangeDresden>`__
- Current maintainer: `Ralf Lange <https://github.com/RalfLangeDresden>`__
- `Contributors <https://github.com/RalfLangeDresden/mopidy-radiobrowser/graphs/contributors>`_
