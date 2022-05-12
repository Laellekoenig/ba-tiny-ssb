import socket
import _thread
import sys
from .html import HTMLVisualizer
import json


# non-micropython import
if sys.implementation.name != "micropython":
    # Optional type annotations are ignored in micropython
    from typing import List


to_response = lambda x: "HTTP/1.0 200 OK\n\n{}".format(x).encode()


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
            self._handle_post(client_sock, request)

        elif "GET" in request[0]:
            self._hanlde_get(client_sock, request)

        else:
            # unrecognized request
            client_sock.close()

    def _handle_post(self, client_sock: socket.socket, request: List[str]) -> None:
        cmd = request[0].split(" ")[1]

        if cmd == "/new_file":
            file_name = json.loads(request[-1])["file_name"]
            self.html.version_manager.create_new_file(file_name)
            page = self.html.get_file(file_name, -1)
            client_sock.sendall(to_response(page))
            client_sock.close()
            return

        if cmd == "/file":
            json_dict = json.loads(request[-1])
            file_name = json_dict["file_name"]
            version = json_dict["version"]
            page = self.html.get_file(file_name, version)
            client_sock.sendall(to_response(page))
            client_sock.close()
            return

        if cmd == "/apply":
            json_dict = json.loads(request[-1])
            file_name = json_dict["file_name"]
            version = json_dict["version"]
            self.html.version_manager.add_apply(file_name, version)
            # send updated file view
            page = self.html.get_file(file_name, -1)
            client_sock.sendall(to_response(page))
            client_sock.close()
            return

        if cmd == "/edit":
            json_dict = json.loads(request[-1])
            file_name = json_dict["file_name"]
            version = json_dict["version"]
            page = self.html.get_edit_file(file_name, version)
            client_sock.sendall(to_response(page))
            client_sock.close()
            return

        # must be update

        if cmd.startswith("/emergency_update"):
            cmd = cmd[len("/emergency_update_"):]  # cut off cmd
            split = cmd.split("_")
            version = int(split[-1])
            file_name = "_".join(split[:-1])

            code = "\n".join(request[15:])
            self.html.version_manager.emergency_update_file(file_name, code, version)
            page = self.html.get_file(file_name, -1)
            client_sock.sendall(to_response(page))
            client_sock.close()
            return

        if cmd.startswith("/update"):
            cmd = cmd[len("/update_"):]  # cut off cmd
            split = cmd.split("_")
            version = int(split[-1])
            file_name = "_".join(split[:-1])
            code = "\n".join(request[15:])
            self.html.version_manager.update_file(file_name, code, version)
            page = self.html.get_file(file_name, version)
            client_sock.sendall(to_response(page))
            client_sock.close()
            return

    def _hanlde_get(self, client_sock: socket.socket, request: List[str]) -> None:
        # extract command
        cmd = request[0].split(" ")[1]

        page = None

        # handle depending on cmd
        if cmd == "/":
            page = self.html.get_index()

        if cmd == "/feed_status":
            page = self.html.get_feed_status()

        if cmd == "/version_status":
            page = self.html.get_version_status()

        if cmd == "/file_browser":
            page = self.html.get_file_browser()

        # if cmd.startswith("/get_file_version"):
            # file_name = cmd[len("/get_file_version_"):]
            # extract version number
            # split = file_name.split("_")
            # version = int(split[-1])
            # file_name = "_".join(split[:-2]) + "." + split[-2]

            # page = self.html.get_file(file_name, version)

        # elif cmd.startswith("/get_file"):
            # file_name = cmd[len("/get_file_"):]
            # split = file_name.split("_")
            # file_name = "_".join(split[:-1]) + "." + split[-1]
            # page = self.html.get_file(file_name)

        if cmd == "/create_new_file":
            page = self.html.get_create_new_file()

        # if cmd.startswith("/apply"):
            # cmd = cmd[len("/apply_"):]  # cut off prefix

            # get version number and file name
            # split = cmd.split("_")
            # v = int(split[-1])
            # file_name = "_".join(split[:-2]) + "." + split[-2]

            # apply update
            # self.html.version_manager.add_apply(file_name, v)

            # serve page
            # page = self.html.get_version_status()

        # if cmd.startswith("/edit"):
            # cmd = cmd[len("/edit_"):]
            # split = cmd.split("_")
            # v = int(split[-1])
            # file_name = "_".join(split[:-2]) + "." + split[-2]
            # page = self.html.get_edit_file(file_name, v)

        if page is None:
            page = self.html.get_404()

        # send requested content
        to_response = lambda x: "HTTP/1.0 200 OK\n\n{}".format(x).encode()
        client_sock.sendall(to_response(page))
        client_sock.close()
