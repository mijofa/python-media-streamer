function update_dir_listing() {
    // FIXME: Render the HTML as a Flask template and do all this in HTML, not JS
    var req = new XMLHttpRequest();
    req.open("GET", "ls.json", true);
    req.onload = function(e) {
        entries = JSON.parse(req.responseText);
        list = document.getElementById("directory-listing");
        if (Object.keys(entries).length == 0) {
            item = document.createElement('li');
            item.innerText = "Directory is empty";
            list.appendChild(item);
        } else {
            current_heading = null;
            for (var entry_index in entries) {
                var entry = entries[entry_index];
                if (entry.is_file & ! entry.mimetype.startsWith('video/')) {
                    // Don't show any files that are not videos
                    continue
                }

                first_letter = entry.sortkey[1][0].toUpperCase()
                if (current_heading != first_letter) {
                    lh = document.createElement('lh');
                    lh.innerText = first_letter;
                    list.appendChild(lh);
                    current_heading = first_letter
                }

                list_item = document.createElement('li');
                link = document.createElement('a');
                list_item.appendChild(link);

                if (entry.preview) {
                    img = document.createElement('img');
                    img.src = "data:image/png;base64," + entry.preview;
                    img.title = entry.name;
                    link.appendChild(img);
                } else {
                    link.innerText = entry.name;
                }
                if (entry.is_file) {
                    link.href = '/watch/' + entry.path;
                    list_item.classList.add('file-entry');
                } else {
                    // entry.path is relative to the media root directory,
                    // I think entry.name will always be just the filename but I'm not certain
                    link.href = entry.name;
                    list_item.classList.add('directory-entry');
                }

                list.appendChild(list_item);
            }
        }
        document.getElementById('loading').remove();
    }
    req.send();

}

window.addEventListener("load", update_dir_listing);
