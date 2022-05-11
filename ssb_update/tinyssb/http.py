import socket
import _thread
import sys
from .html import HTMLVisualizer


# non-micropython import
if sys.implementation.name != "micropython":
    # Optional type annotations are ignored in micropython
    from typing import List


class HTTPServer:

    def __init__(self, html: HTMLVisualizer) -> None:
        self.html = html

    def run(self, sock: socket.socket) -> None:
        while True:
            client_sock, _ = sock.accept()
            _thread.start_new_thread(self._handle_http, (client_sock,))


    def _handle_http(self, client_sock: socket.socket) -> None:
        assert self.html is not None, "no HTMLVisualizer initialized"
        msg = client_sock.recv(4096)

        if len(msg) == 0:
            client_sock.close()
            return

        # get request
        request = msg.decode("utf-8").split("\n")
        if len(request) == 0:
            client_sock.close()
            return

        if "POST" in request[0]:
            # update received
            code = request[15:]
            self._handle_http_update(request[0], client_sock, code)
            client_sock.close()
            return

        get = request[0]
        if "GET" not in get:
            client_sock.close()
            return

        # extract command
        cmd = get.split(" ")[1]

        page = None

        # handle depending on cmd
        if cmd in ["/", "/feed_status"]:
            page = self.html.get_main_menu()

        if cmd == "/version_status":
            page = self.html.get_version_status()

        if cmd == "/file_browser":
            page = self.html.get_file_browser()

        if cmd.startswith("/get_file_version"):
            file_name = cmd[len("/get_file_version_"):]
            # extract version number
            split = file_name.split("_")
            version = int(split[-1])
            file_name = "_".join(split[:-2]) + "." + split[-2]

            page = self.html.get_file(file_name, version)

        elif cmd.startswith("/get_file"):
            file_name = cmd[len("/get_file_"):]
            split = file_name.split("_")
            file_name = "_".join(split[:-1]) + "." + split[-1]
            page = self.html.get_file(file_name)

        if cmd == "/create_new_file":
            page = self.html.get_create_new_file()

        if cmd.startswith("/new_file_"):
            # reformat file name
            file_name = cmd[len("/new_file_"):]
            dot_index= file_name.rfind("_")
            file_name = file_name[:dot_index] + "." + file_name[dot_index + 1:]

            # create new file
            self.html.version_manager.create_new_file(file_name)

            # serve page
            page = self.html.get_file_browser()

        if cmd.startswith("/apply"):
            cmd = cmd[len("/apply_"):]  # cut off prefix

            # get version number and file name
            split = cmd.split("_")
            v = int(split[-1])
            file_name = "_".join(split[:-2]) + "." + split[-2]

            # apply update
            self.html.version_manager.add_apply(file_name, v)

            # serve page
            page = self.html.get_version_status()

        if cmd.startswith("/edit"):
            cmd = cmd[len("/edit_"):]
            split = cmd.split("_")
            v = int(split[-1])
            file_name = "_".join(split[:-2]) + "." + split[-2]
            page = self.html.get_edit_file(file_name, v)

        if page is None:
            page = self.html.get_404()

        # send requested content
        to_response = lambda x: "HTTP/1.0 200 OK\n\n{}".format(x).encode()
        client_sock.sendall(to_response(page))
        client_sock.close()

    def _handle_http_update(self, post: str, client_sock: socket.socket, code: List[str]) -> None:
        assert self.html is not None
        emergency = "emergency_update" in post

        if emergency:
            post = post[len("POST /emergency_update_"):]
        else:
            post = post[len("POST /update_"):]

        cmd = post.split(" ")[0]
        split = cmd.split("_")
        v_num = int(split[-1])
        file_name = "_".join(split[:-2])+ "." + split[-2]

        # join entries of code string
        code_str = "\n".join(code)

        # add update
        if emergency:
            self.html.version_manager.emergency_update_file(file_name, code_str, v_num)
        else:
            self.html.version_manager.update_file(file_name, code_str, v_num)

        # send response
        client_sock.sendall(b"ok")
