import _thread
import json
import socket
import sys
from .html import HTMLVisualizer


# non-micropython import
if sys.implementation.name != "micropython":
    # Optional type annotations are ignored in micropython
    from typing import List


# for sending html pages
to_response = lambda x: "HTTP/1.0 200 OK\n\n{}".format(x).encode()


class HTTPServer:
    """
    Used for managing a HTTP server that serves the tinyssb web gui.
    Allows users to interact with system.
    """
    def __init__(self, html: HTMLVisualizer) -> None:
        self.html = html

    def run(self, sock: socket.socket) -> None:
        """
        Starts an infinite loop, accepting and handling incoming connections.
        """
        while True:
            client_sock, _ = sock.accept()
            _thread.start_new_thread(self._handle_http, (client_sock,))

    def _handle_http(self, client_sock: socket.socket) -> None:
        """
        Handles POST and GET http requests.
        """
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
        """
        Handles POST http requests. Executes the given function and sends
        feedback to client. Closes the connection in the end.
        A 404 page is server in case of an unknown command.
        """
        cmd = request[0].split(" ")[1]

        if cmd in ["/new_file", "/file", "/apply", "/edit"]:
            print(request)
            json_dict = json.loads(request[-1])
            file_name = json_dict["file_name"]


            if cmd == "/new_file":
                self.html.version_manager.create_new_file(file_name)
                page = self.html.get_file(file_name, -1)
                client_sock.sendall(to_response(page))
                client_sock.close()
                return

            version = json_dict["version"]
            page = None

            if cmd == "/file":
                page = self.html.get_file(file_name, version)

            if cmd == "/apply":
                self.html.version_manager.add_apply(file_name, version)
                # send updated file view
                page = self.html.get_file(file_name, -1)

            if cmd == "/edit":
                page = self.html.get_edit_file(file_name, version)

            assert page is not None
            client_sock.sendall(to_response(page))
            client_sock.close()
            return

        emergency = cmd.startswith("/emergency_update")
        update = cmd.startswith("/update")
        if emergency or update:
            # separate command
            cmd = cmd[len("/emergency_update_"):] if emergency else cmd[len("/update_"):]

            # get update info
            split = cmd.split("_")
            version = int(split[-1])
            file_name = "_".join(split[:-1])
            code = "\n".join(request[15:])

            if emergency:
                self.html.version_manager.emergency_update_file(file_name, code, version)
            else:
                self.html.version_manager.update_file(file_name, code, version)

            page = self.html.get_file(file_name, -1)
            client_sock.sendall(to_response(page))
            client_sock.close()
            return

        # default error message
        client_sock.send(to_response(self.html.get_404()))
        client_sock.close()

    def _hanlde_get(self, client_sock: socket.socket, request: List[str]) -> None:
        """
        Handles http GET requests. Fetches the requested page and sends it to client.
        If the page is not found, a 404 page is sent.
        """
        # extract command
        cmd = request[0].split(" ")[1]

        # handle depending on requested page
        page = None
        if cmd == "/":
            page = self.html.get_index()

        if cmd == "/feed_status":
            page = self.html.get_feed_status()

        if cmd == "/version_status":
            page = self.html.get_version_status()

        if cmd == "/file_browser":
            page = self.html.get_file_browser()

        if cmd == "/create_new_file":
            page = self.html.get_create_new_file()

        if page is None:
            page = self.html.get_404()

        # send requested content
        client_sock.sendall(to_response(page))
        client_sock.close()
