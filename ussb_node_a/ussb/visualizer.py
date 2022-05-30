from json import dumps, loads
from ubinascii import hexlify
from .util import listdir
from os import remove


PAGE = """
<!DOCTYPE html>
<html>
    <head>
        <style>
            body {background-color: black;
                  color: white;
                  padding: 2rem;
                  margin: 0;}
            #title {cursor: pointer;
                    text-decoration: underline;
                    margin-top: -1rem;}
            #menu {display: flex;
                   flex-direction: row;}
            .menu_item {margin-right: 1rem;
                        font-family: monospace;}
            a {color: white;}
            h3 {font-family: monospace;}
            #graph_container {display: flex;
                              flex-direction: column;
                              align-items: center;
                              justify-content: center;
                              margin-top: 10vh;
                              margin-bottom: 2rem;}
            #legend {font-family: monospace;}
            ul {list-style-type: square;}
        </style>
    </head>
    <body>
        <h1 onclick='javascript:window.open("/", "_self");' id='title'>tinyssb</h1>
        <div id='menu'>
            <a href='viz' class='menu_item'> visualizer </a>
            <br>
            <a href='feed_status' class='menu_item'> feed_status </a>
            <br>
            <a href='version_status' class='menu_item'> version_status </a>
            <br>
            <a href='file_browser' class='menu_item'> file_browser </a>
        </div>
        <div id="graph_container">
            <h3 id="tick"> 0 </h3>
            <canvas id="graph" width=600 height=600> </canvas>
        </div>
        <div id="legend">
            <ul>
                <li> bright color = incoming packet, blob or request </li>
                <li> dark color = outgoing packet, blob or request </li>
            </ul>
            <a onclick='javascript:window.open("/viz-reset", "_self")' href='javascript:void(0);' > reset </a>
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

                img.data[pixel] = 0;
                img.data[pixel + 1] = 0;
                img.data[pixel + 2] = 0;
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
                        data = JSON.parse(text);
                        update_tick(data);
                    }
                );
            } catch (err) {
                console.log("error when fetching data");
                return;
            }

            // sleep for 1s
            await new Promise(r => setTimeout(r, 500));
        }
    }

    function update_tick(data) {
        let canvas = document.getElementById("graph");
        let ctx = canvas.getContext("2d");
        // clear screen
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        // update tick
        const newestTick = data.ticks[data.ticks.length - 1];
        if (newestTick == undefined) newestTick = 0;
        document.getElementById("tick").innerHTML = newestTick;

        let maxTick = 0;
        for (let i = 0; i < data.fids.length; i++) {
            const fid = data.fids[i];
            const rx = data["RX:" + fid];
            const tx = data["TX:" + fid];

            // find max
            if (rx != undefined && rx[rx.length - 1] > maxTick) maxTick = rx[rx.length - 1];
            if (tx != undefined && tx[tx.length - 1] > maxTick) maxTick = tx[tx.length - 1];
        }

        const height = canvas.height / data.fids.length
        const stepSize = canvas.width / maxTick;

        // draw blocks
        for (let i = 0; i < data.fids.length; i++) {
            const fid = data.fids[i];
            const rx = data["RX:" + fid];
            const tx = data["TX:" + fid];
            const color = "#" + fid.slice(0, 6);

            if (rx != undefined) {
                drawRX(ctx, rx, stepSize, height, i, color);
            }

            if (tx != undefined) {
                drawTX(ctx, tx, stepSize, height, i, color);
            }
        }
    }

    function drawRX(ctx, points, stepSize, height, offset, color) {
        points.forEach(function (point, i) {
            ctx.fillStyle = color;
            ctx.fillRect(point * stepSize, height * offset, stepSize, height);
        });
    }

    function drawTX(ctx, points, stepSize, height, offset, color) {
        ctx.globalAlpha = 0.5;
        points.forEach(function (point, i) {
            ctx.fillStyle = color;
            ctx.fillRect(point * stepSize, height * offset, stepSize, height);
        });
        ctx.globalAlpha = 1;
    }
    </script>
</html>
"""


class Visualizer:

    def __init__(self):
        self.tick = 0
        self.data = {
            "ticks": [],
            "fids": [],
        }
        self._load_data()

    def _load_data(self) -> None:
        if "viz.json" in listdir():
            f = open("viz.json")
            data_dict = loads(f.read())
            f.close()

            self.tick = data_dict["tick"]
            self.data = data_dict["data"]

    def _save_data(self) -> None:
        f = open("viz.json", "w")
        f.write(dumps({"tick": self.tick, "data": self.data}))
        f.close()

    def reset(self) -> None:
        if "viz.json" in listdir():
            remove("viz.json")
        self.tick = 0
        self.data = {
            "ticks": [],
            "fids": [],
        }

    def get_index(self) -> str:
        return PAGE

    def register_tx(self, fid: bytearray) -> None:
        str_fid = hexlify(fid).decode()
        if str_fid not in self.data["fids"]:
            self.data["fids"].append(str_fid)

        str_fid = "TX:{}".format(str_fid)
        if str_fid in self.data:
            self.data[str_fid].append(self.tick)
        else:
            self.data[str_fid] = [self.tick]

        self.data["ticks"].append(self.tick);
        self.tick += 1
        self._save_data()

    def register_rx(self, fid: bytearray) -> None:
        str_fid = hexlify(fid).decode()
        if str_fid not in self.data["fids"]:
            self.data["fids"].append(str_fid)

        str_fid = "RX:{}".format(str_fid)

        if str_fid in self.data:
            self.data[str_fid].append(self.tick)
        else:
            self.data[str_fid] = [self.tick]

        self.data["ticks"].append(self.tick);
        self.tick += 1
        self._save_data()

    def get_data(self) -> str:
        return dumps(self.data)
