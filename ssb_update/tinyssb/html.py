import sys
from .feed_manager import FeedManager
from .ssb_util import to_hex
from .version_manager import VersionManager
from .version_util import apply_changes, jump_versions, string_version_graph, read_file


# non-micropython import
if sys.implementation.name != "micropython":
    # Optional type annotations are ignored in micropython
    from typing import List, Optional


class HTMLVisualizer:
    """
    Class for creating HTML strings.
    GUI of tinyssb.
    """

    # style sheet
    style = """body {padding: 2rem;
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
                              text-decoration: underline;}}"""

    title = """<h1 onclick='javascript:window.open("/", "_self");' id='title'>tinyssb</h1>"""

    menu = """<div id='menu'>
                <a href='feed_status' class='menu_item'> feed_status </a>
                <br>
                <a href='version_status' class='menu_item'> version_status </a>
                <br>
                <a href='file_browser' class='menu_item'> file_browser </a>
              </div>
    """

    get_file_script = """<script>
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
        </script>"""

    # refresh page link: link can be customized
    reload = lambda _, x: "<a href='{}' id='reload'> reload </a>".format(x)

    def __init__(
        self,
        master_fid: bytes,
        feed_manager: FeedManager,
        version_manager: VersionManager,
    ) -> None:
        self._master_fid = master_fid
        self.feed_manager = feed_manager
        self.version_manager = version_manager

    def wrap_html(self, body: str) -> str:
        """
        Creates a full html page from a given body (html) string.
        Adds the style sheet from above.
        """
        html = """<!DOCTYPE html>
                  <html>
                    <head>
                    </head>

                    <style>
                      {}
                    </style>
                    {}
                  </html>""".format(
            self.style, body
        )
        return html

    def bob_the_page_builder(
        self, elements: List[str], script: Optional[str] = None
    ) -> str:
        """
        Takes a list of html elements (as strings) and creates a full html page.
        Adds the style sheet from above.
        """
        body = "\n".join(["<body>"] + elements + ["</body>"])
        if script:
            body = script + "\n" + body
        return self.wrap_html(body)

    def get_index(self) -> str:
        """
        Returns the main menu page as a html string.
        """
        elements = [
            "<div id='index_container'>",
            "<div id='index_aligner'>",
            "<h1 id='index_title'> tinyssb </h1>",
            self.menu,
            "</div>",
            "</div>",
        ]

        return self.bob_the_page_builder(elements)

    def get_feed_status(self) -> str:
        """
        Returns the feed tree visualization as a html string.
        """
        elements = [
            self.title,
            self.reload("/feed_status"),
            self.menu,
            "<h3> feed_status </h3>",
            "<p> <pre>{}</pre> </p>".format(str(self.feed_manager)),
        ]
        return self.bob_the_page_builder(elements)

    def get_version_status(self) -> str:
        """
        Returns the version_status page of the gui.
        Displays all monitored file names and their update fids.
        The version graphs are also displayed.
        """
        assert (
            self.version_manager.vc_feed is not None
        )  # can't construct graphs without

        graphs = []
        for file_name in self.version_manager.vc_dict:
            # get corresponding update feed
            fid, _ = self.version_manager.vc_dict[file_name]
            feed = self.feed_manager.get_feed(fid)
            if feed is None:
                continue

            # get newest apply version number
            newest_apply = self.version_manager.vc_feed.get_newest_apply(fid)
            # construct graph
            str_graph = string_version_graph(feed, self.feed_manager, newest_apply)

            # construct additional html elements
            # graph title
            graph_title = (
                "<a href='javascript:void(0);' onclick='getFile(\"{}\", -1)'>".format(
                    file_name
                )
            )
            graph_title += file_name
            graph_title += "</a>: {}\n".format(to_hex(fid))

            # add to list
            graphs.append(graph_title + str_graph + "\n")

        # connect all graphs in one string
        html_graph = ""
        for graph in graphs:
            html_graph += "<p> <pre class='graph'>{}</pre> <p>".format(graph)

        subtitle = "<h3> version_status </h3>"

        # construct page
        elements = [
            self.title,
            self.reload("/version_status"),
            self.menu,
            subtitle,
            html_graph,
        ]
        return self.bob_the_page_builder(elements, script=self.get_file_script)

    def get_file_browser(self) -> str:
        """
        Returns the file selector as a html string.
        Displays all monitored files and links to their pages.
        """
        # construct file selector
        file_lst = "<ul>\n"
        for file_name in self.version_manager.vc_dict:
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
            self.title,
            self.reload("/file_browser"),
            self.menu,
            subtitle,
            create_file_link,
            file_lst,
        ]
        return self.bob_the_page_builder(elements, script=self.get_file_script)

    def get_file(self, file_name: str, version_num: int = -1) -> str:
        """
        Returns the html file displaying the content of the given file.
        If the version number == -1, the currently applied version is displayed.
        Otherwise, the correct version is shown.
        """
        assert (
            self.version_manager.vc_feed is not None
        )  # needed to get correct versions

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
                        alert('applied_update');
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
        fid = self.version_manager.vc_dict[file_name][0]
        feed = self.feed_manager.get_feed(fid)
        assert feed is not None, "failed to get feed"

        # check if the version number was specified
        newest_apply = self.version_manager.vc_feed.get_newest_apply(fid)
        if version_num == -1:
            version_num = newest_apply

        # read contents of file
        content = read_file(self.version_manager.path, file_name)
        assert content is not None
        # change to correct version if necessary
        if version_num != newest_apply:
            changes = jump_versions(newest_apply, version_num, feed, self.feed_manager)
            content = apply_changes(content, changes)
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
        max_v = feed.get_current_version_num()
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
        return self.bob_the_page_builder(elements, script=self.get_file_script)

    def get_create_new_file(self) -> str:
        """
        Page that allows user to create a new file and add it to version control.
        """
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
            self.title,
            self.reload("create_new_file"),
            self.menu,
            title,
            back_btn,
            padding,
            label,
            input_field,
            "<br>",
            btn,
        ]
        return self.bob_the_page_builder(elements, script=script)

    def get_edit_file(self, file_name: str, version: int) -> str:
        """
        Returns the file editor for the selected file name and version.
        Allows the user to send updates to network (normal and emergency.)
        """
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

        underscore_fn = file_name.replace(".", "_")  # used in links

        script = """<script>
        // bool emergency: determines how update is sent
        async function send(emergency) {{
            text = document.getElementById('code_area').value;

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
                    body: text,
                    headers: {{
                        'Content-Type': 'application/json'
                    }}
                }});

                response.text().then(
                    function(html) {{
                        document.open();
                        document.write(html);
                        document.close();
                        alert('added_update');
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
        </script>""".format(
            file_name, version
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
        reload = self.reload("/edit_{}_{}".format(underscore_fn, version))
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
        emergency_btn += "add_as_emergency_update"
        emergency_btn += "</a>"

        return_link = "<a href='javascript:location.reload();' class='padding_link'>"
        return_link += "&lt_cancel"
        return_link += "</a>"

        padding = (
            "<div id='pad'></div>"  # adding distance between return link and title
        )

        elements = [
            self.title,
            self.menu,
            reload,
            subtitle,
            return_link,
            padding,
            code_area,
            "<br>",
            send_btn,
            emergency_btn,
            script2,
        ]
        return self.bob_the_page_builder(elements, script=script)

    def get_404(self) -> str:
        """
        Contains the default 'page not found' page as a html string.
        """
        subtitle = "<h3> page_not_found </h3>"
        elements = [self.title, self.reload("."), self.menu, subtitle]
        return self.bob_the_page_builder(elements)
