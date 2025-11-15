import tornado.ioloop
import tornado.web

class MainHandler(tornado.web.RequestHandler):
    def get(self):
        self.write("Hello, Tornado!")

def make_app():
    return tornado.web.Application([
        (r"/", MainHandler),
    ])

def main():
    app = make_app()
    port = 8888
    app.listen(port)
    print(f"Tornado server listening on http://127.0.0.1:{port}")
    tornado.ioloop.IOLoop.current().start()

if __name__ == "__main__":
    main()
