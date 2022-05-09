import sys
from .feed_manager import FeedManager
from .version_manager import VersionManager
from .version_util import string_version_graph, read_file
from .ssb_util import to_hex


# non-micropython import
if sys.implementation.name != "micropython":
    # Optional type annotations are ignored in micropython
    pass


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
                       padding: .5rem .5rem .5rem 1rem;}
                #code_container {display: flex;
                                 flex-direction: row;}
                #line_nums {border: 1px solid black;
                            border-right: 0px;
                            color: grey;
                            padding: .5rem 0 .5rem .5rem}"""

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

    wrap_html = lambda self, x: """ <html>
                                        <head>
                                        </head>

                                        <style>
                                            {}
                                        </style>

                                            {}
                                    </html>
                                """.format(self.style, x)

    def __init__(
        self,
        master_fid: bytes,
        feed_manager: FeedManager,
        version_manager: VersionManager,
    ) -> None:
        self._master_fid = master_fid
        self.feed_manager = feed_manager
        self.version_manager = version_manager

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
            html_graph += "<p> <pre>{}</pre> <p>".format(graph)

        html = """  <body>
                        {}
                        {}
                        {}
                        <h3> version_status </h3>
                        {}
                    </body>""".format(
            self.title, self.reload("/version_status"), self.menu, html_graph
        )
        return self.wrap_html(html)

    def get_file_browser(self) -> str:
        file_lst = ""
        html = """  <body>
                        {}
                        {}
                        {}
                    </body>""".format(
                        self.title, self.reload("/file_browser"), self.menu
                    )
        return self.wrap_html(html)

    def get_file(self, file_name: str) -> str:
        dot_index = file_name.rfind("_")
        dot_file_name = file_name[:dot_index] + "." + file_name[dot_index + 1 :]
        content = read_file(self.version_manager.path, dot_file_name)
        line_nums = None
        if content is not None:
            content = content.replace("<", "&lt")
            line_nums = "<br>".join([str(x) for x in range(1, content.count("\n") + 1)])
        html = """  <body>
                        {}
                        {}
                        {}
                        <h3> {} </h3>
                        <div id="code_container">
                            <p id='line_nums'> {}<p>
                            <p> <pre id='code'>{}</pre> </p>
                        </div>
                    </body>""".format(
            self.title,
            self.reload("/get_file_{}".format(file_name)),
            self.menu,
            dot_file_name,
            line_nums,
            content,
        )
        return self.wrap_html(html)
