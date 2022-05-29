from .feed import get_feed, get_newest_apply, get_upd, length
from .feed_manager import FeedManager, get_feed_overview
from .version_manager import VersionManager, string_version_graph, jump_versions, apply_changes
from sys import implementation
from ubinascii import hexlify


# helps with debugging in vim
if implementation.name != "micropython":
    # from typing import List
    from typing import List, Optional


# bodge
class Holder:
    vm = None


# -----------------------------------HTML/CSS-----------------------------------
style = """
body {padding: 2rem;
      margin: 0;}
p {font-family: monospace;}
a {font-family: monospace;}
#title {cursor: pointer;
        text-decoration: underline;
        margin-top: -1rem;}
#menu {display: flex;
       flex-direction: row;}
.menu_item {margin-right: 1rem;}
#reload {position: fixed;
         top: 3rem;
         right: 2rem;}
#code {border: 1px solid black;
       border-left: 0px;
       padding: .5rem .5rem .5rem 1rem;
       min-width: 50%;}
#code_container {display: flex;
                 flex-direction: row;}
#line_nums {border: 1px solid black;
            border-right: 0px;
            color: grey;
            padding: .5rem 0 .5rem .5rem}
.graph {border-bottom: 1px solid black;}
button {margin-top: .5rem;}
.v_num {margin-right: .5rem;}
.padding_link {padding-right: .5rem;}
#code_area {min-width: 50%;}
.ital {font-stlye: italic;}
#version_subtitle {margin-bottom: 0;}
#pad {height: 1rem;}
#current_version {text-decoration: underline black;
                  font-weight: bold;}
#index_container {width: calc(100vw - 4rem);
                  height: calc(100vh - 4rem);
                  display: flex;
                  flex-direction: column;
                  justify-content: center;
                  align-items: center;}
#index_aligner a {padding-left: .5rem;
                  padding-right: .5rem;}
#index_aligner {display: flex;
                flex-direction: column;
                justify-content: start;
                align-items: center;
                margin-bottom: 15vh;
                padding: 1rem;
                padding-left: 1.5rem;}
#index_title {font-size: 3rem;
              margin-left: -.5rem;
              text-decoration: underline;}
#hide {display: none;}}
"""

title = """
<h1 onclick='javascript:window.open("/", "_self");' id='title'>tinyssb</h1>
"""

menu = """
<div id='menu'>
    <a href='feed_status' class='menu_item'> feed_status </a>
    <br>
    <a href='version_status' class='menu_item'> version_status </a>
    <br>
    <a href='file_browser' class='menu_item'> file_browser </a>
</div>
"""

reload = lambda x: "<a href='{}' id='reload'> reload </a>".format(x)

# ----------------------------------JavaScript----------------------------------
get_file_script = """
<script>
async function getFile(fileName, version) {
    try {
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

        response.text().then(
            function(html) {
                //overwrite page
                document.open();
                document.write(html);
                document.close();
            },
            function(err) {alert('failed_to_get_file'); return;}
        );

        return;
    } catch (err) {
        alert('failed_to_get_file');
    }
}
</script>
"""

# ------------------------------------functions----------------------------------
def wrap_html(body: str) -> str:
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
    if script:
        body = "\n".join([script, "<body>"] + elements + ["</body>"])
    else:
        body = "\n".join(["<body>"] + elements + ["</body>"])
    return wrap_html(body)


def get_index() -> str:
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
    elements = [
        title,
        reload("/feed_status"),
        menu,
        "<h3> feed_status </h3>",
        "<p> <pre>{}</pre> </p>".format(get_feed_overview()),
    ]
    return bob_the_page_builder(elements)

def get_version_status() -> str:
    graphs = []
    if type(Holder.vm) is not VersionManager:
        return ""

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

    # connect all graphs in one string
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
    # construct file selector
    if type(Holder.vm) is not VersionManager:
        return ""

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
    if type(Holder.vm) is not VersionManager:
        return ""

    apply_script = """<script>
    async function applyUpdate(file_name, version) {
        try {
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

            response.text().then(
                function(html) {
                    //alert('applied_update');
                    document.open();
                    document.write(html);
                    document.close();
                    return;
                },
                function(err) {
                    alert('failed_to_apply_update');
                }
            );
        } catch (err) {
            alert('failed_to_apply_update');
        }
    }

    async function editFile(file_name, version) {
        try {
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

            response.text().then(
                function(html) {
                    // overwrite page
                    document.open();
                    document.write(html);
                    document.close();
                },

                function(err) {
                    alert('failed_to_get_file_editor');
                    return;
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
        try:
            changes = jump_versions(newest_apply, version_num, feed)
            content = apply_changes(content, changes)
        except Exception:
            content = "Update blob is not fully available yet."
    # make it html proof
    content = content.replace("<", "&lt")
    # create line numbers
    line_nums = "<br>".join([str(x) for x in range(1, content.count("\n") + 2)])
    # html display
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
    max_v = minv + length(feed) - 3
    max_v = 0 if max_v is None else max_v
    # construct html element
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

    # link to editing page
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
    padding = (
        "<div id='pad'></div>"  # adding distance between return link and title
    )

    elements = [
        apply_script,
        title,
        reload("/get_file_{}".format(file_name)),
        menu,
        subtitle,
        return_link,
        padding,
        version_nums,
    ]

    if Holder.vm.may_update:
        elements.append(edit_link)
        elements.append(apply_link)

    elements.append(code_container)
    return bob_the_page_builder(elements, script=get_file_script)


def get_create_new_file() -> str:
    script = """<script>
    async function create_file() {
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
            const response = await fetch("/new_file", {
                method: "POST",
                body: JSON.stringify({
                    'file_name': input,
                }),
                headers: {
                    'Content-Type': 'application/json'
                }
            });

            response.text().then(
                function(html) {
                    document.open();
                    document.write(html);
                    document.close();
                    return;
                },

                function(err) {
                    alert('create_file_failed');
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
    padding = (
        "<div id='pad'></div>"  # adding distance between return link and title
    )
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
    if not type(Holder.vm) is VersionManager:
        return ""

    fid = Holder.vm.vc_dict[file_name][0]
    feed = get_feed(fid)
    assert feed is not None

    vc_feed = get_feed(Holder.vm.vc_fid)
    newest_apply = get_newest_apply(vc_feed, fid)
    if newest_apply is None:
        newest_apply = 0
    f = open(file_name)
    code = f.read()
    f.close()

    if newest_apply != version:
        # get requested version
        changes = jump_versions(newest_apply, version, feed)
        code = apply_changes(code, changes)

    old_code = "<div id ='hide'>{}<div>".format(code)

    underscore_fn = file_name.replace(".", "_")  # used in links

    script = """<script>
    // bool emergency: determines how update is sent
    async function send(emergency) {{
        text = document.getElementById('code_area').value;
        old = document.getElementById('hide').textContent;

        changes = getChanges(old, text);

        if (emergency) {{
            // emergency update
            cmd = '/emergency_update';
        }} else {{
            cmd = '/update';
        }}

        cmd += '_{}_{}'; // file name and version number

        try {{
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

            response.text().then(
                function(html) {{
                    document.open();
                    document.write(html);
                    document.close();
                    //alert('added_update');
                    return;
                }},
                function(err) {{
                    alert('update_failed');
                }}
            );

        }} catch(err) {{
            alert('update_failed')
        }}
    }}

    function getChanges(oldV, newV) {{
        if (oldV === newV) return [];
        mid = extract_lcs(oldV, newV);
        let changes = [];

        let j = 0;
        for (let i = 0; i < oldV.length; i++) {{
            if (oldV[i] !== mid[j]) {{
                const sIdx = i;
                let x = oldV[i];
                while(++i < oldV.length && oldV[i] !== mid[j]) {{
                    x = x.concat(oldV[i]);
                }}
                changes.push([sIdx, 'D', x]);
                i -= 1;
                continue;
            }}
            j += 1;
        }}

        j = 0;
        for (let i = 0; i < newV.length; i++) {{
            if (newV[i] !== mid[j]) {{
                const sIdx = i;
                let x = newV[i];
                while (++i < newV.length && newV[i] !== mid[j]) {{
                    x = x.concat(newV[i]);
                }}

                changes.push([sIdx, 'I', x]);
                i -= 1;
                continue;
            }}
            j += 1;
        }}

        return changes;
    }}

    function extract_lcs(s1, s2) {{
        mov = lcs_grid(s1, s2);
        let lcs = "";

        let i = s1.length - 1;
        let j = s2.length - 1;

        while (i >= 0 && j >= 0) {{
            if (mov[i][j] == 1) {{
                lcs = s1[i] + lcs;
                i--;
                j--;
                continue;
            }}
            if (mov[i][j] == 0) {{
                j--;
                continue;
            }}
            i--;
        }}

        return lcs;
    }}

    function lcs_grid(s1, s2) {{
        const m = s1.length;
        const n = s2.length;

        // left = 0, diagonal = 1, up = 2 
        let mov = new Array(m).fill(-1).map(() => new Array(n).fill(-1));
        let count = new Array(m).fill(0).map(() => new Array(n).fill(0));

        for (let i = 0; i < m; i++) {{
            for (let j = 0; j < n; j++) {{
                if (s1[i] === s2[j]) {{
                    let val = 0;
                    if (i > 0 && j > 0) {{
                        val = count[i - 1][j - 1];
                    }}
                    count[i][j] = val + 1;
                    mov[i][j] = 1;
                }} else {{
                    let top = 0;
                    if (i > 0) {{
                        top = count[i - 1][j];
                    }}

                    let left = 0;
                    if (j > 0) {{
                        left = count[i][j - 1];
                    }}
                    count[i][j] = top >= left ? top : left;
                    mov[i][j] = top >= left ? 2 : 0;
                }}
            }}
        }}
        return mov;
    }}
    </script>""".format(
        file_name, version, file_name, version
    )

    script2 = """<script>
    document.getElementById('code_area').addEventListener('keydown', function(e) {
        if (e.key == 'Tab') {
            e.preventDefault();
            const start = this.selectionStart;
            const end = this.selectionEnd;

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
    reload_btn = reload("/edit_{}_{}".format(underscore_fn, version))
    subtitle = (
        "<h3 id='version_subtitle'> edit: <i>{}</i> at <i>v{}</i></h3>".format(
            file_name, version
        )
    )

    # create editor
    code_area = "<textarea id='code_area' rows=35 cols=80>"
    code_area += code
    code_area += "</textarea>"

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

    padding = (
        "<div id='pad'></div>"  # adding distance between return link and title
    )

    elements = [
        title,
        menu,
        reload_btn,
        subtitle,
        return_link,
        padding,
        code_area,
        "<br>",
        send_btn,
        emergency_btn,
        script2,
        old_code,
    ]
    return bob_the_page_builder(elements, script=script)


def get_404() -> str:
    subtitle = "<h3> page_not_found </h3>"
    elements = [title, reload("."), menu, subtitle]
    return bob_the_page_builder(elements)
