from .feed import get_feed, get_newest_apply, get_upd, length
from .feed_manager import get_feed_overview
from .version_manager import (
    VersionManager,
    jump_versions,
    string_version_graph,
)
from sys import implementation
from ubinascii import hexlify


# helps with debugging in vim
if implementation.name != "micropython":
    from typing import List, Optional


# bodge for fixing circular imports
class Holder:
    vm = None


# -----------------------------------HTML/CSS-----------------------------------
# style sheet of web GUI
style = """
a       {font-family: monospace;}
body    {padding: 2rem;
         margin: 0;}
button  {margin-top: .5rem;}
p       {font-family: monospace;}

.graph          {border-bottom: 1px solid black;}
.ital           {font-stlye: italic;}
.menu_item      {margin-right: 1rem;}
.padding_link   {padding-right: .5rem;}
.v_num          {margin-right: .5rem;}

#code_area          {min-width: 50%;
                     height: 70vh;}
#code               {border: 1px solid black;
                     border-left: 0px;
                     padding: .5rem .5rem .5rem 1rem;
                     min-width: 50%;}
#code_container     {display: flex;
                     flex-direction: row;}
#current_version    {text-decoration: underline black;
                     font-weight: bold;}
#hide               {display: none;}
#index_aligner      {display: flex;
                     flex-direction: column;
                     justify-content: start;
                     align-items: center;
                     margin-bottom: 15vh;
                     padding: 1rem;
                     padding-left: 1.5rem;}
#index_aligner a    {padding-left: .5rem;
                     padding-right: .5rem;}
#index_container    {width: calc(100vw - 4rem);
                     height: calc(100vh - 4rem);
                     display: flex;
                     flex-direction: column;
                     justify-content: center;
                     align-items: center;}
#index_title        {font-size: 3rem;
                     margin-left: -.5rem;
                     text-decoration: underline;}
#line_nums          {border: 1px solid black;
                     border-right: 0px;
                     color: grey;
                     padding: .5rem 0 .5rem .5rem}
#menu               {display: flex;
                     flex-direction: row;}
#pad                {height: 1rem;}
#reload             {position: fixed;
                     top: 3rem;
                     right: 2rem;}
#title              {cursor: pointer;
                     text-decoration: underline;
                     margin-top: -1rem;}
#version_subtitle   {margin-bottom: 0;}
"""

# main title, displayed on every page
title = """
<h1 onclick='javascript:window.open("/", "_self");' id='title'>tinyssb</h1>
"""

# main menu, displayed on every page
menu = """
<div id='menu'>
    <a href='viz' class='menu_item'> visualizer </a>
    <br>
    <a href='feed_status' class='menu_item'> feed_status </a>
    <br>
    <a href='version_status' class='menu_item'> version_status </a>
    <br>
    <a href='file_browser' class='menu_item'> file_browser </a>
</div>
"""

# creates a reload button containing the given link as href
reload = lambda x: "<a href='{}' id='reload'> reload </a>".format(x)

# ----------------------------------JavaScript----------------------------------
# requests the given file name and version from the http server
# version number -1 -> currently applied version
get_file_script = """
<script>
async function getFile(fileName, version) {
    try {
        // send request
        const response = await fetch('/file', {
            method: 'POST',
            body: JSON.stringify({
                'file_name': fileName,
                'version': version,
            }),
            headers: {
                'Content-Type': 'application/json'
            }
        });

        // replace current page with response
        response.text().then(
            function(html) {
                document.open();
                document.write(html);
                document.close();
            }
        );

        return;
    } catch (err) {
        alert('failed_to_get_file');
    }
}
</script>
"""

# longest common substring (LCS) algorithm implementation
# used as a diff algorithm - compute insert and delete operations of update
# first the lcs between two versions is calculated
# the resulting lcs string is compared with the original version
# -> compute needed delete operations
# then the lcs string is compared to the updated version
# -> compute needed insert operations
# these changes are encoded as lists:
# [index_in_string, operation(D/I), inserted/removed string]
lcs_script = """
<script>
function getChanges(oldV, newV) {
    if (oldV === newV) return [];

    // get lcs string
    mid = extract_lcs(oldV, newV);

    // compute insert/delete operations
    let changes = [];

    // start with delete operations -> difference to original
    let j = 0;
    for (let i = 0; i < oldV.length; i++) {
        if (oldV[i] !== mid[j]) {
            // check for consecutive deletions
            const sIdx = i;
            let x = oldV[i];
            while(++i < oldV.length && oldV[i] !== mid[j]) {
                x = x.concat(oldV[i]);
            }
            changes.push([sIdx, 'D', x]);
            i -= 1;
            continue;
        }
        j += 1;
    }


    // compute insert operations -> difference to update
    j = 0;
    for (let i = 0; i < newV.length; i++) {
        if (newV[i] !== mid[j]) {
            // check for consecutive insertions
            const sIdx = i;
            let x = newV[i];
            while (++i < newV.length && newV[i] !== mid[j]) {
                x = x.concat(newV[i]);
            }

            changes.push([sIdx, 'I', x]);
            i -= 1;
            continue;
        }
        j += 1;
    }

    return changes;
}

function extract_lcs(s1, s2) {
    // computes the lcs of two given strings

    // get grid
    mov = lcs_grid(s1, s2);
    let lcs = "";

    // "walk" through grid
    // 0 -> left, 1 -> diagonal, 2 -> up
    let i = s1.length - 1;
    let j = s2.length - 1;

    while (i >= 0 && j >= 0) {
        if (mov[i][j] == 1) {
            lcs = s1[i] + lcs;
            i--;
            j--;
            continue;
        }
        if (mov[i][j] == 0) {
            j--;
            continue;
        }
        i--;
    }

    return lcs;
}

function lcs_grid(s1, s2) {
    // computes the lcs grid of two strings
    const m = s1.length;
    const n = s2.length;

    // left = 0, diagonal = 1, up = 2 
    let mov = new Array(m).fill(-1).map(() => new Array(n).fill(-1));
    let count = new Array(m).fill(0).map(() => new Array(n).fill(0));

    for (let i = 0; i < m; i++) {
        for (let j = 0; j < n; j++) {
            if (s1[i] === s2[j]) {
                let val = 0;
                if (i > 0 && j > 0) {
                    val = count[i - 1][j - 1];
                }
                count[i][j] = val + 1;
                mov[i][j] = 1;
            } else {
                let top = 0;
                if (i > 0) {
                    top = count[i - 1][j];
                }

                let left = 0;
                if (j > 0) {
                    left = count[i][j - 1];
                }
                count[i][j] = top >= left ? top : left;
                mov[i][j] = top >= left ? 2 : 0;
            }
        }
    }
    return mov;
}
</script>
"""

# ------------------------------------functions----------------------------------
def wrap_html(body: str) -> str:
    """
    Adds header and style sheet to given body and wraps everything in HTML tags.
    """
    html = """
    <!DOCTYPE html>
    <html>
        <head>
        </head>

        <style>
            {}
        </style>
        {}
    </html>""".format(
        style, body
    )
    return html


def bob_the_page_builder(elements: List[str], script: Optional[str] = None) -> str:
    """
    Constructs a full HTML page from given list of HTML elements (placed in body).
    If provided, also adds javascript code (must be wrapped in <script> tags)
    above body.
    """
    if script:
        body = "\n".join([script, "<body>"] + elements + ["</body>"])
    else:
        body = "\n".join(["<body>"] + elements + ["</body>"])
    return wrap_html(body)


def get_index() -> str:
    """
    Returns the main page.
    """
    elements = [
        "<div id='index_container'>",
        "<div id='index_aligner'>",
        "<h1 id='index_title'> tinyssb </h1>",
        menu,
        "</div>",
        "</div>",
    ]

    return bob_the_page_builder(elements)


def get_feed_status() -> str:
    """
    Returns a visualization of all local feeds.
    """
    elements = [
        title,
        reload("/feed_status"),
        menu,
        "<h3> feed_status </h3>",
        "<p> <pre>{}</pre> </p>".format(get_feed_overview()),
    ]
    return bob_the_page_builder(elements)


def get_version_status() -> str:
    """
    Returns a visualization of all files that are currently monitored by the
    version manager. Also displays their individual update trees.
    """
    graphs = []
    if type(Holder.vm) is not VersionManager:
        return get_404()

    # go over every monitored file
    for file_name in Holder.vm.vc_dict:
        # get corresponding update feed
        fid, _ = Holder.vm.vc_dict[file_name]
        feed = get_feed(fid)
        if feed is None:
            continue

        # get newest apply version number
        vf_feed = get_feed(Holder.vm.vc_fid)
        newest_apply = get_newest_apply(vf_feed, feed.fid)
        # construct graph
        str_graph = string_version_graph(feed, newest_apply)

        # construct additional html elements
        # graph title
        graph_title = (
            "<a href='javascript:void(0);' onclick='getFile(\"{}\", -1)'>".format(
                file_name
            )
        )
        graph_title += file_name
        graph_title += "</a>: {}\n".format(hexlify(fid).decode())

        # add to list
        graphs.append(graph_title + str_graph + "\n")

    # connect all graphs into single string
    html_graph = ""
    for graph in graphs:
        html_graph += "<p> <pre class='graph'>{}</pre> <p>".format(graph)

    subtitle = "<h3> version_status </h3>"

    # construct page
    elements = [
        title,
        reload("/version_status"),
        menu,
        subtitle,
        html_graph,
    ]
    return bob_the_page_builder(elements, script=get_file_script)


def get_file_browser() -> str:
    """
    Returns a visualization of all monitored files without their version trees
    (faster, especially on pycom devices). Also allows user to create new files.
    """
    if type(Holder.vm) is not VersionManager:
        return get_404()

    # construct file selector
    file_lst = "<ul>\n"
    for file_name in Holder.vm.vc_dict:
        file_lst += """<li>
                         <a href='javascript:void(0);'
                            onclick='getFile(\"{}\", -1)'>
                           {}
                         </a>
                        </li>""".format(
            file_name, file_name
        )
    file_lst += "</ul>"

    # additional gui elements
    subtitle = "<h3> file_browser </h3>"
    create_file_link = "<a href='create_new_file'> create_new_file </a>"

    elements = [
        title,
        reload("/file_browser"),
        menu,
        subtitle,
    ]

    if Holder.vm.may_update:
        elements.append(create_file_link)

    elements.append(file_lst)
    return bob_the_page_builder(elements, script=get_file_script)


def get_file(file_name: str, version_num: int = -1) -> str:
    """
    Returns a visualization of the requested file and version.
    On the master node, updates may be applied and files edited.
    """
    if type(Holder.vm) is not VersionManager:
        return get_404()

    apply_script = """<script>
    async function applyUpdate(file_name, version) {
        try {
            // send apply request to server
            const response = await fetch('/apply', {
                method: 'POST',
                body: JSON.stringify({
                    'file_name': file_name,
                    'version': version,
                }),
                headers: {
                    'Content-Type': 'application/json',
                }
            });

            // replace current page with response
            response.text().then(
                function(html) {
                    document.open();
                    document.write(html);
                    document.close();
                }
            );
        } catch (err) {
            alert('failed_to_apply_update');
        }
    }

    async function editFile(file_name, version) {
        try {
            // request editor of current file and version
            const response = await fetch('/edit', {
                method: 'POST',
                body: JSON.stringify({
                    'file_name': file_name,
                    'version': version,
                }),
                headers: {
                    'Content-Type': 'application/json',
                }
            });

            // replace current page with editor
            response.text().then(
                function(html) {
                    document.open();
                    document.write(html);
                    document.close();
                }
            );

        } catch(err) {
            alert('failed_to_get_file_editor');
        }
    }
    </script>"""

    # get corresponding feed and newest apply
    fid = Holder.vm.vc_dict[file_name][0]
    feed = get_feed(fid)
    assert feed is not None, "failed to get feed"

    # check if the version number was specified
    assert Holder.vm.vc_fid is not None
    vc_feed = get_feed(Holder.vm.vc_fid)
    newest_apply = get_newest_apply(vc_feed, feed.fid)
    if newest_apply is None:
        newest_apply = 0
    if version_num == -1:
        version_num = newest_apply

    # read contents of file
    f = open(file_name)
    content = f.read()
    f.close()

    # change to correct version if necessary
    if version_num != newest_apply:
        # FIXME: error handling in jump versions instead
        try:
            content = jump_versions(content, newest_apply, version_num, feed)
        except Exception:
            content = "Update blob is not fully available yet."

    # make content HTML proof
    content = content.replace("<", "&lt")

    # create line numbers
    line_nums = "<br>".join([str(x) for x in range(1, content.count("\n") + 2)])
    # display code
    code_container = """<div id="code_container">
                          <p id='line_nums'> {} <p>
                          <p> <pre id='code'>{}</pre> </p>
                        </div>""".format(
        line_nums, content
    )

    # get list of all version numbers -> find max version
    fn_v_tuple = get_upd(feed)
    assert fn_v_tuple is not None
    _, minv = fn_v_tuple
    max_v = (
        minv + length(feed) - 3
    )  # assuming that is correctly formatted file update feed
    max_v = 0 if max_v is None else max_v

    # add buttons for switching file versions
    version_nums = [
        """<a href='javascript:void(0);'
              onclick='getFile(\"{}\", {})'
              class='v_num'>
             v{}
           </a>""".format(
            file_name, v, v
        )
        for v in range(max_v + 1)
        if v != version_num  # do not add link for current version
    ]
    current_version = "<a class='v_num' id='current_version'>"
    current_version += "v{}".format(version_num)
    current_version += "</a>"
    version_nums.insert(version_num, current_version)  # insert at correct position
    version_nums = "\n".join(["<div>"] + version_nums + ["</div>"])

    # create apply links (only for updates that are not applied)
    if version_num != newest_apply:
        apply_link = """<a href='javascript:void(0);'
                           onclick='applyUpdate(\"{}\", {})'>
                          apply_version
                        </a>""".format(
            file_name, version_num
        )
    else:
        apply_link = "<a></a>"

    # link to file editor
    edit_link = """<a href='javascript:void(0);'
                      onclick='editFile(\"{}\", {})'
                      class='padding_link'>
                     edit
                   </a>""".format(
        file_name, version_num
    )

    # link back to version_status page
    return_link = "<a href='javascript:location.reload();'> &lt_back </a>"

    subtitle = "<h3 id='version_subtitle'> {} </h3>".format(file_name)
    padding = "<div id='pad'></div>"  # adding distance between return link and title

    elements = [
        apply_script,
        title,
        # FIXME: reload button to file
        menu,
        subtitle,
        return_link,
        padding,
        version_nums,
    ]

    # only allow edits and update applications on master
    if Holder.vm.may_update:
        elements.append(edit_link)
        elements.append(apply_link)

    elements.append(code_container)
    return bob_the_page_builder(elements, script=get_file_script)


def get_create_new_file() -> str:
    """
    Returns the page for creating new files.
    """
    script = """<script>
    async function create_file() {
        // get name of new file
        input = document.getElementById('input').value;

        // check if input is valid
        if (input.includes(" ") ||
            input === "" ||
            input.split(".").length > 2) {

            alert("invalid_file_name");
            return;
        }

        // cut off starting /
        if (input.startsWith("/")) {
            input = input.slice(1);
        }

        try {
            // send request to server
            const response = await fetch("/new_file", {
                method: "POST",
                body: JSON.stringify({
                    'file_name': input,
                }),
                headers: {
                    'Content-Type': 'application/json'
                }
            });

            // open newly created file
            response.text().then(
                function(html) {
                    document.open();
                    document.write(html);
                    document.close();
                    return;
                }
            );

        } catch (err) {
            alert('create_file_failed');
        }
    }
    </script>"""

    # html elements
    title = "<h3 id='version_subtitle'> create_new_file </h3>"
    back_btn = "<a href='file_browser'> &lt_back </a>"
    padding = "<div id='pad'></div>"  # adding distance between return link and title
    label = "<label> new_file_name: </label>"
    input_field = "<input type='text' id='input'> </input>"
    btn = "<button onclick=create_file()> create_file </button>"

    elements = [
        title,
        reload("create_new_file"),
        menu,
        title,
        back_btn,
        padding,
        label,
        input_field,
        "<br>",
        btn,
    ]
    return bob_the_page_builder(elements, script=script)


def get_edit_file(file_name: str, version: int) -> str:
    """
    Returns the file editor for the given file name and version.
    """
    if not type(Holder.vm) is VersionManager:
        return get_404()

    # get corresponding feed
    fid = Holder.vm.vc_dict[file_name][0]
    feed = get_feed(fid)
    assert feed is not None

    # get currently applied version number
    vc_feed = get_feed(Holder.vm.vc_fid)
    newest_apply = get_newest_apply(vc_feed, fid)
    if newest_apply is None:
        newest_apply = 0  # nothing applied yet

    # read file
    f = open(file_name)
    code = f.read()
    f.close()

    # get requested version
    if newest_apply != version:
        code = jump_versions(code, newest_apply, version, feed)

    # code is set to hidden div element
    # this is for fixing issues with directly setting text to TextArea element
    old_code = "<div id ='hide'>{}</div>".format(code)

    script = """
{}
<script>
function setText() {{
    // setup set text to text area, fixes issues with TextArea
    let txtArea = document.getElementById("code_area");
    txtArea.value = document.getElementById("hide").textContent;
}}

async function send(emergency) {{
    // computes the changes between two versions and sends them to server
    // this is done using lcs (defined above)
    // bool emergency: determines how update is sent

    text = document.getElementById('code_area').value;
    old = document.getElementById('hide').textContent;
    changes = getChanges(old, text);

    if (emergency) {{
        cmd = '/emergency_update';
    }} else {{
        cmd = '/update';
    }}

    try {{
        // send request to server
        const response = await fetch(cmd, {{
            method: 'POST',
            body: JSON.stringify({{
                'file_name': '{}',
                'version': {},
                'changes': changes,
            }}),
            headers: {{
                'Content-Type': 'application/json'
            }}
        }});

        // replace editor with file view
        response.text().then(
            function(html) {{
                document.open();
                document.write(html);
                document.close();
                return;
            }}
        );

    }} catch(err) {{
        alert('update_failed')
    }}
}}
</script>""".format(
        lcs_script,
        file_name,
        version,
    )

    script2 = """<script>
    document.getElementById('code_area').addEventListener('keydown', function(e) {
        // tabs do not swicth focus, enter 4 spaces in text area
        if (e.key == 'Tab') {
            e.preventDefault();
            const start = this.selectionStart;
            const end = this.selectionEnd;

            // insert 4 spaces
            this.value = this.value.substring(0, start)
                + '   ' 
                + this.value.substring(end);
            this.selectionStart = start + 4;
            this.selectionEnd = start + 4;
        }
    });
    </script>
    """

    # build html elements
    reload_btn = reload("javascript:setText();")
    subtitle = "<h3 id='version_subtitle'> edit: <i>{}</i> at <i>v{}</i></h3>".format(
        file_name, version
    )

    # create editor
    code_area = "<textarea id='code_area' cols=80></textarea>"
    send_btn = (
        "<a href='javascript:void(0);' onclick='send(false)' class='padding_link'>"
    )
    send_btn += "add_update"
    send_btn += "</a>"

    emergency_btn = (
        "<a href='javascript:void(0);' onclick='send(true)' class='padding_link'>"
    )
    emergency_btn += "add_and_apply"
    emergency_btn += "</a>"

    return_link = "<a href='javascript:location.reload();' class='padding_link'>"
    return_link += "&lt_cancel"
    return_link += "</a>"

    padding = "<div id='pad'></div>"  # adding distance between return link and title

    elements = [
        title,
        menu,
        reload_btn,
        subtitle,
        return_link,
        padding,
        send_btn,
        emergency_btn,
        padding,
        code_area,
        script2,
        old_code,
        "<script> setText(); </script>",
    ]
    return bob_the_page_builder(elements, script=script)


def get_404() -> str:
    """
    Returns the page containing the "file not found" error message.
    """
    subtitle = "<h3> page_not_found </h3>"
    elements = [title, reload("."), menu, subtitle]
    return bob_the_page_builder(elements)
