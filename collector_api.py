import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer


HOST = "0.0.0.0"
PORT = int(os.getenv("PORT", "8080"))


class CollectorAPI(BaseHTTPRequestHandler):

    def send_json(self, data, status=200):

        body = json.dumps(
            data,
            ensure_ascii=False,
            indent=2
        ).encode("utf-8")

        self.send_response(status)

        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8"
        )

        self.send_header(
            "Content-Length",
            str(len(body))
        )

        self.end_headers()

        self.wfile.write(body)

    def do_GET(self):

        if self.path == "/":

            self.send_json({
                "name": "dewu-flip-monitor collector",
                "status": "running",
                "service": "自建商品数据接口",
                "endpoint": "/products"
            })

            return

        if self.path == "/products":

            self.send_json({
                "products": []
            })

            return

        if self.path == "/health":

            self.send_json({
                "status": "ok"
            })

            return

        self.send_json(
            {
                "error": "not_found"
            },
            404
        )


def main():

    server = HTTPServer(
        (HOST, PORT),
        CollectorAPI
    )

    print(
        f"自建数据接口启动：http://{HOST}:{PORT}",
        flush=True
    )

    server.serve_forever()


if __name__ == "__main__":
    main()
