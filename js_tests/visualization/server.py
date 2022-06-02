import sys
from socket import socket, AF_INET, SOCK_STREAM, SOL_SOCKET, SO_REUSEADDR, getaddrinfo
from _thread import start_new_thread

page = """
<!DOCTYPE html>
<html>
    <head>
        <style>
            body {background-color: black;
                  color: white;
                  padding: 0;
                  margin: 0;}
            #title {font-family: monospace;
                    font-size: 2rem;
                    height: calc(10vh - 4rem);
                    padding: 2rem;}
            #graph_container {height: 90vh;
                              display: flex;
                              justify-content: center;
                              align-items: center;}
            #graph {margin-bottom: 15vh;
                    border: 2px solid white;}
        </style>
    </head>
    <body>
        <div id="title"> Hello world! </div>
        <div id="graph_container">
            <canvas id="graph" width=800 height=800> </canvas>
        </div>
    </body>
    <script>
    setup();
    connect();

    function setup() {
        let canvas = document.getElementById("graph");
        let ctx = canvas.getContext("2d");

        const w = canvas.width;
        const h = canvas.height;

        let img = ctx.createImageData(w, h);

        for (let i = 0; i < w; i++) {
            for (let j = 0; j < h; j++) {
                const pixel = (j * w + i) * 4;

                img.data[pixel] = 255;
                img.data[pixel + 1] = 0;
                img.data[pixel + 2] = 255;
                img.data[pixel + 3] = 255;
            }
         }

         ctx.putImageData(img, 0, 0);
    }

    async function connect() {
        while (true) {

            try {
                const response = await fetch('/viz', {
                    method: 'POST',
                    body: JSON.stringify('test'),
                    headers: {
                        'Content-Type': 'application/json'
                    }
                });

                response.text().then(
                    function(text) {
                        g = document.getElementById("title");
                        g.textContent = text;
                    }
                );
            } catch (err) {
                console.log("error when fetching data");
                return;
            }

            // sleep for 2s
            await new Promise(r => setTimeout(r, 2000));
        }
    }
    </script>
</html>
"""


COUNT = 0
to_response = lambda x: "HTTP/1.0 200 OK\n\n{}".format(x).encode()


def send_index(client: socket) -> None:
    client.send(to_response(page))
    client.close()


def send_data(client: socket) -> None:
    global COUNT
    client.send(to_response("test {}".format(COUNT)))
    COUNT += 1
    client.close()


def handle_client(client: socket) -> None:
    msg = client.recv(4096)

    if len(msg) == 0:
        client.close()
        return

    request = msg.decode("utf-8").split("\n")

    if "GET" in request[0]:
        send_index(client)
    elif "POST" in request[0]:
        send_data(client)
    else:
        client.close()


def server_loop(server) -> None:
    while True:
        client, _ = server.accept()
        start_new_thread(handle_client, (client,))


def main() -> int:
    server = socket(AF_INET, SOCK_STREAM)
    server.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
    server.bind(getaddrinfo("0.0.0.0", 8000)[0][-1])
    server.listen(5)
    server_loop(server)
    return 0


if __name__ == "__main__":
    sys.exit(main())
