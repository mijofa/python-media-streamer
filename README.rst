Python Media Streamer
=====================
First up, this name is bad but I'm not very creative.

The point of this project is to have something kinda like Netflix but self-hosted.
There's a few pre-existing projects that aim to provide similar, but there's various issues with them that make them unsuitable for my use:

* `Streama <https://github.com/streamaserver/streama>`_ doesn't have Chromecast support (yet?) or the server-side transcoding needed to make casting work.
  I don't know any Java and as such can't really contribute to speed up the process with those features
* `Emby <https://github.com/MediaBrowser/Emby>`_ started violating the GPL badly, and doing various things that make me nervous about the project.
  I'm unwilling to contribute to this project because of their seemingly uncaring attitude to their own license violations.
* `Plex <https://www.plex.tv/>`_ relies on a closed-source backend component, and requires authenticating to their remote server to use your local install.
  The functionality might be fine for me, but I think it defeats the purpose of both open-source and self-hosting


So the goal with this is to start with having a simple web interface that provides a browser for my local video files (music & playlists as a future enhancement) that will serve out those video files in a format supported by the Chromecast, prefferably without transcoding files that are already supported. As I understand it, I can leave the Chromecast support for the HTML/JS code, so I'm going to focus mostly on the Python code for now and leave that for the 2nd step.


TODO
====
* Implement WakeLock as per spec at https://www.w3.org/TR/wake-lock/
