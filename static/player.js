// I want this set in the global scope because I know everything function here is going to use it.
// Plus, it makes console debugging easier.
var video_player;

var controls_timer = null;

function controlsShow(duration = 0) {
    controls = document.getElementById("video-controls");
    controls.classList.remove("hidden");
    document.body.classList.remove("hide-mouse");

    /* Move the subtitles up so the controls are not in the way */
    document.getElementById("auto-subs-style").innerHTML = "::-webkit-media-text-track-container { bottom: "+controls.offsetHeight+"px; }";

    if (controls_timer) {
        controls_timer = clearTimeout(controls_timer);
    }
    if (duration > 0) {
        controls_timer = setTimeout(controlsHide, duration * 1000);
    }
}
function controlsHide() {
    controls = document.getElementById("video-controls");
    controls.classList.add("hidden");
    document.body.classList.add("hide-mouse");

    /* Put the subtitles back where they belong */
    document.getElementById("auto-subs-style").innerHTML = "";

    /* Remove the hide timer in case it's been hidden manually before the timer expires*/
    if (controls_timer) {
        controls_timer = clearTimeout(controls_timer);
    }
}

function videoPauseToggle() {
    if (video_player.paused == true)
         {video_player.play()  }
    else {video_player.pause() }
};

function videoMuteToggle() {
    if (video_player.muted == false)
         {video_player.muted = true  }
    else {video_player.muted = false }
}

function secondsToString(seconds) {
    hours   = Math.floor( seconds / 3600 );
    minutes = Math.floor( ( seconds - ( hours * 3600 ) ) / 60 );
    seconds = Math.round( seconds - ( minutes * 60 ) - ( hours * 3600 ))

    ret_str = ''

    h = hours.toString()
    while (h.length < 2) {
        h = "0" + h;
    }

    m = minutes.toString()
    while (m.length < 2) {
        m = "0" + m;
    }
    
    s = seconds.toString()
    while (s.length < 2) {
        s = "0" + s;
    }

    return h+":"+m+":"+s
}

function _videoSeekBeyondDuration(time, unpause) {
    if (time >= video_player.total_duration) {
        console.log("Seeking beyond end of file, I don't know how to deal with this yet");
    } else {
        // Jump to the specified time regardless of the current duration to keep the buffer going.
        video_player.currentTime = time;
        if (time > video_player.duration) {
            // FIXME: I don't like overwriting the event functions,
            // but it's the easiest way I could find that lets me clear it without knowing the response from addEventListener
            if (video_player.ondurationchange == null || video_player.ondurationchange == undefined) {
                video_player.ondurationchange = function(ev) {
                    // FIXME: Wait, time and unpause shouldn't be set in this context... why does this work?
                    //        I think I just don't understand JS contexts
                    _videoSeekBeyondDuration(time, unpause)
                };
            };
        } else {
            video_player.ondurationchange = undefined;
            // Duration has caught up, let's continue
            // FIXME: Getting a lot of this error when seeking around quickly:
            //        > Uncaught (in promise) DOMException: The play() request was interrupted by a call to pause(). https://goo.gl/LdLk22
            if (unpause && video_player.paused) {
                video_player.play()
            };
        }
    }
}
function videoSeek(time) {
    // The browser might not yet have cached what's being seeked to,
    // or the server might not even have transcoded that part yet.
    // So if seeking beyond what the browser thinks is the current end time,
    // just wait for the cache to catch up but keep jumping forward to keep the browser focused.
    //
    // FIXME: Figure out seeking beyond the currently buffered duration.
    //        Perhaps this requires pausing until duration >= seeked_time
    if (time >= video_player.total_duration) {
        console.log("Seeking beyond end of file, I don't know how to deal with this yet");
    } else {
        if (video_player.paused != true) {
            was_paused = false;
            video_player.pause();
        } else {
            was_paused = true;
        }
        _videoSeekBeyondDuration(time, !was_paused)
    }
}

function videoFullscreenToggle() {
    player = document.getElementById('video-container');
    if (document.webkitIsFullScreen) {
        document.webkitCancelFullScreen();
	} else {
        player.webkitRequestFullscreen();
	}
}

function setup_controls() {
    // Buttons
    var playButton = document.getElementById("play-pause");
    var muteButton = document.getElementById("mute");
    var fullScreenButton = document.getElementById("full-screen");
    // Sliders
    var volumeBar = document.getElementById("volume-bar");
    var brightnessBar = document.getElementById("brightness-bar");
    var seekBar = document.getElementById("seek-bar");

    var seekableCanvas = document.getElementById("seekable-canvas");
    var seekableContext = seekableCanvas.getContext('2d');
    var bufferedCanvas = document.getElementById("buffered-canvas");
    var bufferedContext = bufferedCanvas.getContext('2d');

    // FIXME: Is "click" the right event to use?
    playButton.addEventListener("click", videoPauseToggle);
    // Update the pause button on state change
    video_player.addEventListener("pause", ev => playButton.innerHTML = "&#x25B6;");
    video_player.addEventListener("play",  ev => playButton.innerHTML = "|&nbsp;|");
    

    // FIXME: Is "click" the right event to use?
    muteButton.addEventListener("click", videoMuteToggle);
    // Event listener for the volume bar
    volumeBar.addEventListener("input", ev => video_player.volume = ev.target.valueAsNumber / ev.target.max );

    // Update the mute button & volume slider on state change
    video_player.addEventListener("volumechange", function(ev) {
        volumeBar.value = ev.target.volume * volumeBar.max;
        volumeBar.title = volumeBar.value + "%";
        if (ev.target.muted == false)
             {muteButton.classList.remove('active-button') }
        else {muteButton.classList.add('active-button')    }
    });
    // Simply trigger ^ that event listener, so I don't need to pre-initialise the HTML correctly.
    // FIXME: Should I perhaps split that into a usable function and run the function directly?
    video_player.dispatchEvent(new CustomEvent("volumechange", {}))
    

    // Can't determine the length of the video in JS alone until the entire cache is filled,
    // so let's ask the server to check the duration of the pre-transcoded file.
    var req = new XMLHttpRequest();
    req.open("GET", document.URL+"/duration", true);
    req.onload = function(e) {
        video_player.total_duration = parseFloat(req.responseText);
        seekBar.max = video_player.total_duration;
        document.getElementById("position-end").innerHTML = secondsToString(video_player.total_duration)
    }
    req.send()

    // Event listener for the seek bar
    seekBar.addEventListener("change", ev => videoSeek(ev.target.valueAsNumber));
    
    // Update the seek bar as the video plays
    video_player.addEventListener("timeupdate", function() {
        seekBar.value = video_player.currentTime;
        document.getElementById("position-current").innerHTML = secondsToString(video_player.currentTime)
    });
    
    // Pause the video when the slider handle is being dragged
    seekBar.addEventListener("mousedown", _ => video_player.pause());
    // Play the video when the slider handle is dropped
    seekBar.addEventListener("mouseup",   _ => video_player.play());

    /* Display progress of the seekable data */
    /* This should effectively be what the server has transcoded so far */
    var seekableCanvasStyle = window.getComputedStyle(seekableCanvas);
    seekableContext.fillStyle = seekableCanvasStyle.getPropertyValue('color');
    seekableContext.strokeStyle = seekableContext.fillStyle;
    var bufferedCanvasStyle = window.getComputedStyle(bufferedCanvas);
    bufferedContext.fillStyle = bufferedCanvasStyle.getPropertyValue('color');
    bufferedContext.strokeStyle = bufferedContext.fillStyle;

    var update_canvases = function() {
        var inc = seekableCanvas.width / video_player.total_duration
        for (i=0; i<video_player.seekable.length; i++) {
            var startX = video_player.seekable.start(i) * inc;
            var endX = video_player.seekable.end(i) * inc;
            var width = endX - startX;

            seekableContext.rect(startX, 0, width, seekableCanvas.height);
            seekableContext.fill();
            seekableContext.stroke();
        }

        var inc = bufferedCanvas.width / video_player.total_duration
        for (i=0; i<video_player.buffered.length; i++) {
            var startX = video_player.buffered.start(i) * inc;
            var endX = video_player.buffered.end(i) * inc;
            var width = endX - startX;

            bufferedContext.rect(startX, 0, width, bufferedCanvas.height);
            bufferedContext.fill();
            bufferedContext.stroke();
        }
    };

    video_player.addEventListener("durationchange", update_canvases)
    video_player.addEventListener("progress", update_canvases)
    
    // Event listener for the brightness bar
    // NOTE: Those are backticks, NOT single-quotes.
    //       This makes it an ES6 template string, which allows variable substitution/etc,
    //       but is not supported by all browsers.
    //       https://developers.google.com/web/updates/2015/01/ES6-Template-Strings
    // FIXME: Make ViM understand that so that syntax-highlighting works better
    // FIXME: Don't completely overwrite all filters just to change the brightness one.
    brightnessBar.addEventListener("input", function(ev) {
        ev.target.title = ev.target.value + "%";
        video_player.style.filter = `brightness(${ev.target.valueAsNumber}%)`
    });
    
    // Event listener for the full-screen button
    // FIXME: Is "click" the right event to use?
    fullScreenButton.addEventListener("click", videoFullscreenToggle);
    window.addEventListener('webkitfullscreenchange',function(ev) {
        if (document.webkitIsFullScreen) {
            fullScreenButton.classList.add('active-button');
        } else {
            fullScreenButton.classList.remove('active-button');
        }
    });
    window.addEventListener("dblclick", videoFullscreenToggle, false);


    // Keyboard shortcuts

    // I'm basing thse keybindings on YouTube's as documented at https://support.google.com/youtube/answer/7631406?hl=en
    // Directional arrow keys do not trigger the keypress event, so must use keydown
    function process_keydown(key_ev) {
        // ARROWS
        switch (key_ev.key) {
            case "ArrowUp":
                console.debug("Raising volume due to user keypress");
                video_player.volume += 0.02
                break;
            case "ArrowDown":
                console.debug("Lowering volume due to user keypress");
                video_player.volume -= 0.02
                break;
            case "ArrowLeft":
                console.debug("Seeking backward 10s due to user keypress");
                videoSeek(video_player.currentTime - 10);
                break;
            case "ArrowRight":
                console.debug("Seeking forward 25s due to user keypress");
                videoSeek(video_player.currentTime + 25);
                key_ev.preventDefault();
                break;
            case "Home":
                console.debug("Seeking to the beginning due to user keypress");
                videoSeek(0);
                break;
            case "End":
                console.debug("Seeking to the end due to user keypress");
                videoSeek(video_player.duration);
                break;
            case "PageDown":
                console.debug("Seeking forward 10m due to user keypress");
                videoSeek(video_player.currentTime + 600);  // 10 minutes forward
                break;
            case "PageUp":
                console.debug("Seeking backward 9m due to user keypress");
                videoSeek(video_player.currentTime - 540);  // 9 minutes back
                break;
            case " ":
                console.debug("Toggling pause due to user keypress");
                videoPauseToggle();
                break;
            case "F11": // FIXME: Chrome's F11 triggered fullscreen is completely different and undetectable from the JS triggered fullscreen, so I'm bypassing it
            case "f":
                console.debug("Toggling fullscreen due to user keypress");
                videoFullscreenToggle();
                break;
            case "m":
                console.debug("Toggling mute due to user keypress");
                videoMuteToggle();
                break;
            case "s":
                console.debug("Toggling subtitles due to user keypress");
                if (vtt_track.track.mode == "showing") {
                    vtt_track.track.mode = "disabled"
                } else {
                    vtt_track.track.mode = "showing"
                }
                break;
            default:
                console.debug("user pressed unconfigured key "+key_ev.code);
                return
        }
        // The 'default' case above will return out of this function if the event wasn't handled here,
        // otherwise if we have handled the event, we want none of the default handlers to have an effect.
        console.debug("Preventing default");
        key_ev.preventDefault();
    }
    window.addEventListener("mousemove", _ => controlsShow(3));
    window.addEventListener("keydown",   _ => controlsShow(3));
    window.addEventListener("keydown", process_keydown);
}


function add_subtitles() {
    // FIXME: Implement a subtitle chooser for language selection/etc
    vtt_track = document.createElement("track");
    vtt_track.kind = "captions";  // FIXME: This is dynamic, don't hard-code it!
    vtt_track.srclang = "eng";  // FIXME: This is dynamic, don't hard-code it!
    vtt_track.language = "English";  // FIXME: This is dynamic, don't hard-code it!
    vtt_track.src = document.URL+'/subtitles.vtt';
    video_player.append(vtt_track);
    vtt_track.addEventListener("load", _ => console.debug("Loaded subtitles"));
    vtt_track.addEventListener("load", _ => this.mode = "showing");
//    // FIXME: Internet said Firefox needs this too
//    vtt_track.addEventListener("load", _ => video_player.textTracks[0].mode = "showing");
    // FIXME: They don't actually trigger until the mode is set to 'showing',
    vtt_track.mode = "showing";
    // FIXME: That doesn't work either... Just go add UI buttons
}

function init_hls() {
    /* Chrome/etc doesn't actually support HLS out of the box, so lets fix that.
     * This is just the Getting Started example from the hls.js documentation
     */
    if(Hls.isSupported()) {
        var hls = new Hls({startPosition: 0});
        hls.loadSource(document.URL+'/hls-manifest.m3u8');
        hls.attachMedia(video_player);
        hls.on(Hls.Events.MANIFEST_PARSED,function() {
            // FIXME: Add a delay here to get some buffering done first.
            //        Trigger on the canplaythrough event instead?
            video_player.play();
        });
    }
    // hls.js is not supported on platforms that do not have Media Source Extensions (MSE) enabled.
    // When the browser has built-in HLS support (check using `canPlayType`), we can provide an HLS manifest (i.e. .m3u8 URL) directly to the video element throught the `src` property.
    // This is using the built-in support of the plain video element, without using hls.js.
    // Note: it would be more normal to wait on the 'canplay' event below however on Safari (where you are most likely to find built-in HLS support) the video_player.src URL must be on the user-driven
    // white-list before a 'canplay' event will be emitted; the last video event that can be reliably listened-for when the URL is not on the white-list is 'loadedmetadata'.
    else if (video_player.canPlayType('application/vnd.apple.mpegurl')) {
        video_player.src = document.URL+'/hls-manifest.m3u8';
        video_player.addEventListener('loadedmetadata',function() {
            video_player.currentTime = 0;
            video_player.play();
        });
    }
}

function setup_casting() {
    /* Chromecast integration
     * This is haphazardly thrown together from Google's Geting started documentation
     */
    // This depends on a thing in the flask app that responds to requests for "/get_ip" with the server's IP address.
    // This is only needed because Chromecast is fucking stupid with DNS and refuses to use any network internal DNS servers.
    var castingMediaURL

    var req = new XMLHttpRequest();
    req.open("GET", "/get_ip", true);
    req.onload = function(e) {
        var a = document.createElement('a');
        a.href = document.URL+'/hls-manifest.m3u8';
        a.hostname = req.responseText;
        castingMediaURL = a.href;
    }
    req.send()
    
    
    window['__onGCastApiAvailable'] = function(loaded, errorInfo) {
      if (loaded) {
        initializeCastApi();
      } else {
        console.log(errorInfo);
      }
    }
    
    initializeCastApi = function() {
      var sessionRequest = new chrome.cast.SessionRequest(chrome.cast.media.DEFAULT_MEDIA_RECEIVER_APP_ID);
      var apiConfig = new chrome.cast.ApiConfig(sessionRequest,
        sessionListener,
        receiverListener);
      chrome.cast.initialize(apiConfig, onInitSuccess, onError);
    };
    
    function onInitSuccess() {console.log("Casting initialised")}
    function onError(error) {console.error(error)}
    
    function receiverListener(e) {
      if( e === chrome.cast.ReceiverAvailability.AVAILABLE) {
        console.log("Chromecast listeners are available")
      }
    }
    
    function onRequestSessionSuccess(e) {
        console.log("Got session");
        session = e;
    }
    
    // My own convenience functions
    set_media = function() {
        var mediaInfo = new chrome.cast.media.MediaInfo(castingMediaURL, 'application/x-mpegURL');
        var request = new chrome.cast.media.LoadRequest(mediaInfo);
        session.loadMedia(request,
           onMediaDiscovered.bind(this, 'loadMedia'),
           onError);
        
        function onMediaDiscovered(how, media) {
           currentMedia = media;
        }
        console.log("Media set")
    }
    init_cast = function() {
        chrome.cast.requestSession(onRequestSessionSuccess, onError);
    }
    
    function onMediaDiscovered(how, media) {
      media.addUpdateListener(onMediaStatusUpdate);
    }
    
    function sessionListener(e) {
      session = e;
      if (session.media.length != 0) {
        onMediaDiscovered('onRequestSessionSuccess', session.media[0]);
      }
    }
    
    // if (session.status !== chrome.cast.SessionStatus.CONNECTED) {
    //     console.log('SessionListener: Session disconnected');
    //     // Update local player to disconnected state
    // }
    
    function stopApp() {
      session.stop(onSuccess, onError);
    }
}

var init_cast;
var set_media;
window.onload = function() {
    video_player = document.getElementById("video-player");

    setup_controls();
    
    init_hls();

    add_subtitles();
    
    // NotYetImplemented
    setup_casting();
}
