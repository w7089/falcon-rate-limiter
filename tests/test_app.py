import falcon
from dateutil.relativedelta import relativedelta

from limiter.core import FalconRateLimiter


def create_app():
    limiter = FalconRateLimiter()

    class TestResource:
        @limiter.rate_limit(requests=2, per=relativedelta(seconds=1))
        def on_get(self, req, resp):
            resp.status = falcon.HTTP_200
            resp.text = "OK"

    @limiter.rate_limit(requests=2, per=relativedelta(seconds=1))
    class ClassDecoratedResource:
        def on_get(self, req, resp):
            resp.status = falcon.HTTP_200
            resp.text = "CLASS OK"

        def on_post(self, req, resp):
            resp.status = falcon.HTTP_200
            resp.text = "CLASS POST OK"

    app = falcon.App()
    app.add_route("/test", TestResource())
    app.add_route("/class-test", ClassDecoratedResource())
    return app


def create_async_app():
    limiter = FalconRateLimiter()

    class AsyncTestResource:
        @limiter.rate_limit(requests=2, per=relativedelta(seconds=1))
        async def on_get(self, req, resp):
            resp.status = falcon.HTTP_200
            resp.text = "ASYNC OK"

    @limiter.rate_limit(requests=2, per=relativedelta(seconds=1))
    class AsyncClassDecoratedResource:
        async def on_get(self, req, resp):
            resp.status = falcon.HTTP_200
            resp.text = "ASYNC CLASS OK"

    app = falcon.asgi.App()
    app.add_route("/async-test", AsyncTestResource())
    app.add_route("/async-class-test", AsyncClassDecoratedResource())
    return app
