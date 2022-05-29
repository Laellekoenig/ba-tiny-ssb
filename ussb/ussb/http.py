from .html import (
    get_404,
    get_create_new_file,
    get_edit_file,
    get_feed_status,
    get_file,
    get_file_browser,
    get_version_status,
)
from .html import get_index
from .util import PYCOM
from .version_manager import VersionManager
from json import loads
from sys import implementation
from usocket import socket


# helps with debugging in vim
if implementation.name != "micropython":
    from typing import List


# bodge
class Holder:
    vm = None


# for sending html pages
to_response = lambda x: "HTTP/1.0 200 OK\n\n{}".format(x).encode()


def run_http(sock: socket) -> None:
    while True:
        client, _ = sock.accept()
        msg = client.recv(4096)

        if len(msg) == 0:
            client.close()
            continue

        request = msg.decode("utf-8").split("\n")

        if "POST" in request[0]:
            _handle_post(client, request)
        elif "GET" in request[0]:
            _handle_get(client, request)
        else:
            client.close()


def _handle_get(client: socket, request: List[str]) -> None:
    cmd = request[0].split(" ")[1]
    del request

    # handle depending on requested page
    page = None
    if cmd == "/":
        page = get_index()

    if cmd == "/feed_status":
        page = get_feed_status()

    if cmd == "/version_status":
        page = get_version_status()

    if cmd == "/file_browser":
        page = get_file_browser()

    if cmd == "/create_new_file":
        page = get_create_new_file()

    if page is None:
        page = get_404()

    # send requested content
    client.send(to_response(page))
    client.close()


def _handle_post(client: socket, request: List[str]) -> None:
    cmd = request[0].split(" ")[1]

    if cmd in ["/new_file", "/file", "/apply", "/edit"]:
        json_dict = loads(request[-1])
        del request
        file_name = json_dict["file_name"]

        if cmd == "/new_file":
            if type(Holder.vm) is not VersionManager:
                client.close()
                return

            Holder.vm.create_new_file(file_name)
            page = get_file(file_name, -1)
            client.send(to_response(page))
            client.close()
            return

        version = json_dict["version"]
        del json_dict
        page = None

        if cmd == "/file":
            page = get_file(file_name, version)

        if cmd == "/apply":
            if type(Holder.vm) is not VersionManager:
                client.close()
                return
            Holder.vm.add_apply(file_name, version)
            page = get_file(file_name, -1)

        if cmd == "/edit":
            page = get_edit_file(file_name, version)

        assert page is not None
        client.send(to_response(page))
        client.close()
        return

    emergency = cmd.startswith("/emergency_update")
    update = cmd.startswith("/update")
    if emergency or update:
        # separate command
        cmd = cmd[len("/emergency_update_") :] if emergency else cmd[len("/update_") :]

        # get update info
        split = cmd.split("_")
        version = int(split[-1])
        file_name = "_".join(split[:-1])
        del split

        req_dict = loads(request[-1])
        file_name = req_dict["file_name"]
        v_num = req_dict["version"]
        changes = req_dict["changes"]

        if type(Holder.vm) is not VersionManager:
            client.close()
            return

        if emergency:
            Holder.vm.emergency_update_file(file_name, changes, v_num)
        else:
            Holder.vm.update_file(file_name, changes, v_num)

        page = get_file(file_name, -1)
        client.send(to_response(page))
        client.close()
        return

    p_404 = None
    client.send(to_response(p_404))
    client.close()
