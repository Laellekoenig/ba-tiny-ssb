import sys
from .feed_manager import FeedManager
from .version_manager import VersionManager
from .version_util import apply_changes, jump_versions, string_version_graph, read_file
from .ssb_util import to_hex


# non-micropython import
if sys.implementation.name != "micropython":
    # Optional type annotations are ignored in micropython
    from typing import List


class HTMLVisualizer:

    style = """body {padding: 2rem;
                     margin: 0;}
               p {font-family: monospace;}
               a {font-family: monospace;}
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
                #pad {height: 1rem;}}"""

    title = """<h1>tinyssb</h1>"""

    menu = """<div id='menu'>
                <a href='feed_status' class='menu_item'> feed_status </a>
                <br>
                <a href='version_status' class='menu_item'> version_status </a>
                <br>
                <a href='file_browser' class='menu_item'> file_browser </a>
              </div>
    """

    reload = lambda _, x: "<a href='{}' id='reload'> reload </a>".format(x)

    wrap_html = lambda self, x: """ <!DOCTYPE html>
                                    <html>
                                        <head>
                                        </head>

                                        <style>
                                            {}
                                        </style>

                                            {}
                                    </html>
                                """.format(
        self.style, x
    )

    def __init__(
        self,
        master_fid: bytes,
        feed_manager: FeedManager,
        version_manager: VersionManager,
    ) -> None:
        self._master_fid = master_fid
        self.feed_manager = feed_manager
        self.version_manager = version_manager

    def body_builder(self, elements: List[str]) -> str:
        opening_tag = "<body>"
        closing_tag = "</body>"
        return "\n".join([opening_tag] + elements + [closing_tag])

    def get_main_menu(self) -> str:
        html = """  <body>
                        {}
                        {}
                        {}
                        <h3> feed_status </h3>
                        <p>
                            <pre>{}</pre>
                        </p>
                    </body>
        """.format(
            self.title, self.reload("."), self.menu, str(self.feed_manager)
        )

        return self.wrap_html(html)

    def get_version_status(self) -> str:
        assert self.version_manager.vc_feed is not None
        graphs = []
        for file_name in self.version_manager.vc_dict:
            fid, _ = self.version_manager.vc_dict[file_name]
            feed = self.feed_manager.get_feed(fid)

            if feed is None:
                continue

            apply = self.version_manager.vc_feed.get_newest_apply(fid)
            split = file_name.split(".")
            file_link = "get_file_{}_{}".format(split[0], split[1])
            graph_title = "<a href='{}'>{}</a>: {}\n".format(
                file_link, file_name, to_hex(fid)
            )
            graphs.append(
                graph_title
                + string_version_graph(feed, self.feed_manager, apply)
                + "\n"
            )

        html_graph = ""
        for graph in graphs:
            html_graph += "<p> <pre class='graph'>{}</pre> <p>".format(graph)

        subtitle = "<h3> version_status </h3>"
        elements = [
            self.title,
            self.reload("/version_status"),
            self.menu,
            subtitle,
            html_graph,
        ]
        return self.wrap_html(self.body_builder(elements))

    def get_file_browser(self) -> str:
        file_lst = "<ul>\n"
        for file_name in self.version_manager.vc_dict:
            link = "get_file_" + file_name.replace(".", "_")
            file_lst += "<li> <a href='{}'> {} </a> </li>\n".format(link, file_name)
        file_lst += "</ul>"

        html = """  <body>
                        {}
                        {}
                        {}
                        <h3> file_browser </h3>
                        <a href='create_new_file'> create_new_file </a>
                        {}
                    </body>""".format(
            self.title, self.reload("/file_browser"), self.menu, file_lst
        )
        return self.wrap_html(html)

    def get_file(self, file_name: str, version: bool = False) -> str:
        assert self.version_manager.vc_feed is not None
        if version:
            # extract and remove version numberget_file_version()
            v = file_name.split("_")[-1]
            cut_index = len(file_name) - len(v) - 1  # - 1 for removed "_"
            file_name = file_name[:cut_index]

        dot_index = file_name.rfind("_")
        dot_file_name = file_name[:dot_index] + "." + file_name[dot_index + 1 :]
        content = read_file(self.version_manager.path, dot_file_name)

        fid = self.version_manager.vc_dict[dot_file_name][0]
        feed = self.feed_manager.get_feed(fid)
        assert feed is not None
        max_v = feed.get_current_version_num()
        if max_v is None:
            max_v = 0
        version_nums = [
            "<a href='{}' class='v_num'> v{} </a>".format(
                "get_file_version_{}_{}".format(file_name, v), v
            )
            for v in range(max_v + 1)
        ]
        version_nums = "\n".join(["<div>"] + version_nums + ["</div>"])

        # version titles
        current_apply = self.version_manager.vc_feed.get_newest_apply(fid)
        if version:
            version_title = "v" + v
        else:
            v = current_apply
            version_title = "v{}".format(current_apply)

        # change file if necessary
        if version and content is not None:
            changes = jump_versions(current_apply, int(v), feed, self.feed_manager)
            content = apply_changes(content, changes)

        line_nums = None
        if content is not None:
            content = content.replace("<", "&lt")
            line_nums = "<br>".join([str(x) for x in range(1, content.count("\n") + 2)])

        if version and int(v) != current_apply:
            apply_link = "<a href='apply_{}_{}'> apply_version </a>".format(
                file_name, v
            )
        else:
            apply_link = "<a> </a>"

        edit_link = "<a href='{}' class='padding_link'> edit </a>".format("/edit_{}_{}".format(file_name, v))
        return_link = "<a href='version_status'> &lt_back </a>"

        subtitle = "<h3 id='version_subtitle'> {}: {} </h3>".format(dot_file_name, version_title)
        code_container = """<div id="code_container">
                                <p id='line_nums'> {}<p>
                                <p> <pre id='code'>{}</pre> </p>
                            </div>""".format(line_nums, content)
        padding = "<div id='pad'></div>"
        elements = [
            self.title,
            self.reload("/get_file_{}".format(file_name)),
            self.menu,
            subtitle,
            return_link,
            padding,
            version_nums,
            edit_link,
            apply_link,
            code_container,
        ]

        return self.wrap_html(self.body_builder(elements))

    def get_create_new_file(self) -> str:
        html = """  <script>
                        function snd() {{
                            input = document.getElementById('input').value;
                            input = input.replace('.', '_');

                            // check if input is valid
                            if (input.includes(" ") ||
                                input === "" ||
                                input.split(".").length > 1) {{
                                alert("invalid_file_name");
                                return;
                            }}

                            window.open("/new_file_" + input, "_self");
                        }}
                    </script>
                    <body>
                        {}
                        {}
                        {}
                        <h3> create_new_file </h3>
                        <label> new_file_name: </label>
                        <input type="text" id='input'> </input>
                        <br>
                        <button onclick=snd()> create_file </button>
                    </body>""".format(
            self.title, self.reload("/create_new_file"), self.menu
        )
        return self.wrap_html(html)

    def get_new_file(self) -> str:
        html = """<script> window.location.href = 'file_browser' </script>"""
        return self.wrap_html(html)

    def get_edit_file(self, file_name: str, version: int) -> str:
        assert self.version_manager.vc_feed is not None

        fid = self.version_manager.vc_dict[file_name][0]
        feed = self.feed_manager.get_feed(fid)
        assert feed is not None

        newest_apply = self.version_manager.vc_feed.get_newest_apply(fid)
        code = read_file(self.version_manager.path, file_name)
        assert code is not None

        if newest_apply != version:
            # get requested version
            changes = jump_versions(newest_apply, version, feed, self.feed_manager)
            code = apply_changes(code, changes)

        script = """<script>
                        async function send(emergency) {{
                            text = document.getElementById('code_area').value;

                            if (emergency) {{
                                cmd = "/emergency_update";
                            }} else {{
                                cmd = "/update";
                            }}

                            cmd += "_{}_{}";

                            try {{
                                const response = await fetch(cmd, {{
                                    method: "POST",
                                    body: JSON.stringify(text),
                                    headers: {{
                                        "Content-Type": "application/json"
                                    }}
                                }});
                                if (response.ok) {{
                                    window.open("/version_status", "_self");
                                    return;
                                }}
                            }}

                            catch(err) {{
                                alert("update_failed")
                            }}
                        }}
                    </script>""".format(file_name.replace(".", "_"), version)

        reload = self.reload("/edit_{}_{}".format(file_name.replace(".", "_"), version))
        subtitle = "<h3> edit: <i>{}</i> at <i>v{}</i></h3>".format(file_name, version)
        code_area = "<textarea id='code_area' rows=35 cols=80>{}</textarea>".format(code)
        send_btn = "<a href='#' onclick='send(false)' class='padding_link'> add_update </a>"
        emergency_btn = "<a href='#' onclick='send(true)' class='padding_link'> add_as_emergency_update </a>"
        elements = [self.title, self.menu, reload, subtitle, code_area, "<br>", send_btn, emergency_btn]
        return self.wrap_html(script + self.body_builder(elements))

    def get_404(self) -> str:
        subtitle = "<h3> page_not_found </h3>"
        elements = [self.title, self.reload("."), self.menu, subtitle]
        return self.wrap_html(self.body_builder(elements))
