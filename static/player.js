// // Not implemented yet
// function update_buffer() {
//     var video = document.getElementById("video-player");
//     var seekBar = document.getElementById("seek-bar");
//         s = "linear-gradient(to right, white, "
//         var i
//         for (i = 0; i < video.buffered.length; i++) {
//             start = ( vidLength - video.buffered.start(i) ) / 100
//             end = ( vidLength - video.buffered.end(i) ) / 100
//             // NOTE: Those are backticks, NOT single-quotes.
//             //       This makes it an ES6 template string, which allows variable substitution/etc,
//             //       but is not supported by all browsers.
//             //       https://developers.google.com/web/updates/2015/01/ES6-Template-Strings
//             s = s + `white ${start}%, red ${end}%, `
//         }
//         s = s + "white)"
//         seekBar.style.background = s
// }

function setup_controls(video) {
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

    // Event listener for the play/pause button
    // FIXME: Is "click" the right event to use?
    playButton.addEventListener("click", function() {
      if (video.paused == true) {
        // Play the video
        video.play();
      } else {
        // Pause the video
        video.pause();
      }
    });
    video.addEventListener("pause", function() {
        // Update the button text to 'Play'
        // FIXME: Style this better
        playButton.innerHTML = "&#x25B6;";
    });
    video.addEventListener("play", function() {
        // Update the button text to 'Pause'
        // FIXME: Style this better
        playButton.innerHTML = "|&nbsp;|";
    });
    
    // Event listener for the mute button
    // FIXME: Is "click" the right event to use?
    muteButton.addEventListener("click", function() {
      if (video.muted == false) {
        // Mute the video
        video.muted = true;
      } else {
        // Unmute the video
        video.muted = false;
      }
    });
    video.addEventListener("volumechange", function() {
      // FIXME: Update the volume slider as well
      if (video.muted == false) {
        // Update the button text
        muteButton.classList.remove('active-button');
      } else {
        // Update the button text
        muteButton.classList.add('active-button');
      }
    });
    // Simply trigger ^ that event listener, so I don't need to pre-initialise the HTML correctly.
    // Should I perhaps split that into a usable function and run the function directly?
    video.dispatchEvent(new CustomEvent("volumechange", {}))
    
    // Event listener for the full-screen button
    // FIXME: Is "click" the right event to use?
    fullScreenButton.addEventListener("click", function() {
        player = document.getElementById('video-container');
        if (document.webkitIsFullScreen) {
            if (document.cancelFullScreen) {  
                document.cancelFullScreen();
            } else if (document.mozCancelFullScreen) {  
                document.mozCancelFullScreen();  // Firefox
            } else if (document.webkitCancelFullScreen) {  
                document.webkitCancelFullScreen();  // Webkit, Chrome/etc
            } else if (document.webkitCancelFullScreen) {  
                document.msCancelFullScreen();  // IE/Edge
            }  
            fullScreenButton.classList.remove('active-button');
		} else {
            if (player.requestFullscreen) {
                player.requestFullscreen();
            } else if (player.mozRequestFullScreen) {
                player.mozRequestFullScreen();  // Firefox
            } else if (player.webkitRequestFullscreen) {
                player.webkitRequestFullscreen();  // Webkit, Chrome/etc
            } else if (player.msRequestFullscreen) {
                player.msRequestFullscreen();  // IE/Edge
            }
            fullScreenButton.classList.add('active-button');
		}
    });
    
    // Can't determine the length of the video in JS alone until the entire cache is filled, so let's ask the server.
    var req = new XMLHttpRequest();
    req.open("GET", document.URL+"/duration", true);
    req.onload = function(e) {
        vidLength = parseFloat(req.responseText);
        seekBar.max = vidLength;
    }
    req.send()

    // Event listener for the seek bar
    seekBar.addEventListener("change", function() {
        // Update the video time
        // FIXME: Figure out seeking beyond the currently buffered duration.
        //        Perhaps this requires pausing until duration >= seeked_time
        video.currentTime = seekBar.value;
    });
    
    // Update the seek bar as the video plays
    video.addEventListener("timeupdate", function() {
      // Update the slider value
      seekBar.value = video.currentTime;
    });
    
    // Pause the video when the slider handle is being dragged
    seekBar.addEventListener("mousedown", function() {
      video.pause();
    });
    // Play the video when the slider handle is dropped
    seekBar.addEventListener("mouseup", function() {
      video.play();
    });

    /* Display progress of the buffered data */
    bufferedCanvasStyle = window.getComputedStyle(bufferedCanvas);
//    bufferedContext.fillStyle = bufferedCanvasStyle.getPropertyValue('background-color');;
//    bufferedContext.fillRect(0, 0, bufferedCanvas.width, bufferedCanvas.height);
    bufferedContext.fillStyle = bufferedCanvasStyle.getPropertyValue('color');
    video.addEventListener("progress", function() {
        var inc = bufferedCanvas.width / vidLength
        for (i=0; i<video.buffered.length; i++) {
            var startX = video.buffered.start(i) * inc;
            var endX = video.buffered.end(i) * inc;
            var width = endX - startX;

            bufferedContext.fillRect(startX, 0, width, bufferedCanvas.height);
        }
    });
    
    /* Display progress of the seekable data */
    /* This should effectively be what the server has transcoded so far */
    seekableCanvasStyle = window.getComputedStyle(seekableCanvas);
    seekableContext.fillStyle = seekableCanvasStyle.getPropertyValue('background-color');
    seekableContext.fillRect(0, 0, seekableCanvas.width, seekableCanvas.height);
    seekableContext.fillStyle = seekableCanvasStyle.getPropertyValue('color');
    video.addEventListener("progress", function() {
        var inc = seekableCanvas.width / vidLength
        for (i=0; i<video.seekable.length; i++) {
            var startX = video.seekable.start(i) * inc;
            var endX = video.seekable.end(i) * inc;
            var width = endX - startX;

            seekableContext.fillRect(startX, 0, width, seekableCanvas.height);
        }
    });
    
    // Event listener for the volume bar
    volumeBar.addEventListener("change", function() {
      // Update the video volume
      video.volume = volumeBar.value;
    });
    
    // Event listener for the brightness bar
    brightnessBar.addEventListener("input", function() {
      // Update the video brightness
      // NOTE: Those are backticks, NOT single-quotes.
      //       This makes it an ES6 template string, which allows variable substitution/etc,
      //       but is not supported by all browsers.
      //       https://developers.google.com/web/updates/2015/01/ES6-Template-Strings
      // FIXME: Make ViM understand that so that syntax-highlighting works better
      // FIXME: Don't completely overwrite all filters just to change the brightness one.
      video.style.filter = `brightness(${brightnessBar.value}%)`;
    });
}

function init_hls(video) {
    /* Chrome/etc doesn't actually support HLS out of the box, so lets fix that.
     * This is just the Getting Started example from the hls.js documentation
     */
    if(Hls.isSupported()) {
        var hls = new Hls();
        hls.loadSource(document.URL+'/hls-manifest.m3u8');
        hls.attachMedia(video);
        hls.on(Hls.Events.MANIFEST_PARSED,function() {
            // FIXME: Add a delay here to get some buffering done first.
            //        Trigger on the canplaythrough event instead?
            video.play();
        });
    }
    // hls.js is not supported on platforms that do not have Media Source Extensions (MSE) enabled.
    // When the browser has built-in HLS support (check using `canPlayType`), we can provide an HLS manifest (i.e. .m3u8 URL) directly to the video element throught the `src` property.
    // This is using the built-in support of the plain video element, without using hls.js.
    // Note: it would be more normal to wait on the 'canplay' event below however on Safari (where you are most likely to find built-in HLS support) the video.src URL must be on the user-driven
    // white-list before a 'canplay' event will be emitted; the last video event that can be reliably listened-for when the URL is not on the white-list is 'loadedmetadata'.
    else if (video.canPlayType('application/vnd.apple.mpegurl')) {
        video.src = document.URL+'/hls-manifest.m3u8';
        video.addEventListener('loadedmetadata',function() {
            video.play();
        });
    }
}

function setup_casting() {
    /* Chromecast integration
     * This is haphazardly thrown together from Google's Geting started documentation
     */
    // This depends on a thing in the flask app that responds to requests for "/get_ip" with the server's IP address.
    // This is only needed because Chromecast is fucking stupid with DNS and refuses to use any network internal DNS servers.
    var req = new XMLHttpRequest();
    req.open("GET", "/get_ip", true);
    req.onload = function(e) { server_ip = req.responseText }
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
    function onError(error) {console.log("ERROR!");console.log(error)}
    
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
    function init_cast() {
        chrome.cast.requestSession(onRequestSessionSuccess, onError);
    }
    currentMediaURL = document.URL+'/hls-manifest.m3u8';
    function set_media() {
    	var mediaInfo = new chrome.cast.media.MediaInfo(currentMediaURL, 'application/x-mpegURL');
    	var request = new chrome.cast.media.LoadRequest(mediaInfo);
    	session.loadMedia(request,
    	   onMediaDiscovered.bind(this, 'loadMedia'),
    	   onError);
    	
    	function onMediaDiscovered(how, media) {
    	   currentMedia = media;
    	}
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

window.onload = function() {
    var video_player = document.getElementById("video-player");

    setup_controls(video_player);
    
    init_hls(video_player);
    
    // // NotYetImplemented
    // setup_casting()
}
