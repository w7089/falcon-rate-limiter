import falcon
import falcon.asgi
from dateutil.relativedelta import relativedelta
from typing import Any, cast

from limiter import FalconRateLimitMiddleware, FalconRateLimiter


def create_app() -> falcon.App:
    limiter = FalconRateLimiter()

    def client_key(req: falcon.Request) -> str:
        return req.get_header("X-Client-Id") or req.remote_addr or "global"

    class TestResource:
        @limiter.rate_limit(requests=2, per=relativedelta(seconds=1))
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.status = falcon.HTTP_200
            resp.text = "OK"

    class PerClientResource:
        @limiter.rate_limit(
            requests=1, per=relativedelta(seconds=1), key_func=client_key
        )
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.status = falcon.HTTP_200
            resp.text = "PER CLIENT OK"

    class CustomMessageResource:
        @limiter.rate_limit(
            requests=1,
            per=relativedelta(seconds=1),
            error_message="Too fast, slow down",
        )
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.status = falcon.HTTP_200
            resp.text = "CUSTOM OK"

    @limiter.rate_limit(requests=2, per=relativedelta(seconds=1))
    class ClassDecoratedResource:
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.status = falcon.HTTP_200
            resp.text = "CLASS OK"

        def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.status = falcon.HTTP_200
            resp.text = "CLASS POST OK"

    @limiter.rate_limit(requests=1, per=relativedelta(seconds=1), key_func=client_key)
    class ClassPerClientResource:
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.status = falcon.HTTP_200
            resp.text = "CLASS PER CLIENT OK"

    app = falcon.App()
    app.add_route("/test", TestResource())
    app.add_route("/per-client", PerClientResource())
    app.add_route("/custom-message", CustomMessageResource())
    app.add_route("/class-test", ClassDecoratedResource())
    app.add_route("/class-per-client", ClassPerClientResource())
    return app


def create_async_app() -> falcon.asgi.App:
    limiter = FalconRateLimiter()

    def client_key(req: falcon.Request) -> str:
        return req.get_header("X-Client-Id") or req.remote_addr or "global"

    class AsyncTestResource:
        @limiter.rate_limit(requests=2, per=relativedelta(seconds=1))
        async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.status = falcon.HTTP_200
            resp.text = "ASYNC OK"

    class AsyncPerClientResource:
        @limiter.rate_limit(
            requests=1, per=relativedelta(seconds=1), key_func=client_key
        )
        async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.status = falcon.HTTP_200
            resp.text = "ASYNC PER CLIENT OK"

    class AsyncCustomMessageResource:
        @limiter.rate_limit(
            requests=1,
            per=relativedelta(seconds=1),
            error_message="Async too fast",
        )
        async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.status = falcon.HTTP_200
            resp.text = "ASYNC CUSTOM OK"

    @limiter.rate_limit(requests=2, per=relativedelta(seconds=1))
    class AsyncClassDecoratedResource:
        async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.status = falcon.HTTP_200
            resp.text = "ASYNC CLASS OK"

    app = falcon.asgi.App()
    app.add_route("/async-test", AsyncTestResource())
    app.add_route("/async-per-client", AsyncPerClientResource())
    app.add_route("/async-custom-message", AsyncCustomMessageResource())
    app.add_route("/async-class-test", AsyncClassDecoratedResource())
    return app


def create_middleware_app(limit_undecorated_routes: bool = True) -> falcon.App:
    limiter = FalconRateLimiter(limit_undecorated_routes=limit_undecorated_routes)
    middleware = FalconRateLimitMiddleware(
        limiter,
        requests=1,
        per=relativedelta(seconds=1),
    )

    class MiddlewareProtectedResource:
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.status = falcon.HTTP_200
            resp.text = "MIDDLEWARE OK"

    class DecoratedResource:
        @limiter.rate_limit(requests=2, per=relativedelta(seconds=1))
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.status = falcon.HTTP_200
            resp.text = "DECORATED OK"

    app = falcon.App(middleware=[middleware])
    app.add_route("/middleware-test", MiddlewareProtectedResource())
    app.add_route("/middleware-decorated", DecoratedResource())
    return app


def create_async_middleware_app(
    limit_undecorated_routes: bool = True,
) -> falcon.asgi.App:
    limiter = FalconRateLimiter(limit_undecorated_routes=limit_undecorated_routes)
    middleware = FalconRateLimitMiddleware(
        limiter,
        requests=1,
        per=relativedelta(seconds=1),
    )

    class AsyncMiddlewareProtectedResource:
        async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.status = falcon.HTTP_200
            resp.text = "ASYNC MIDDLEWARE OK"

    class AsyncDecoratedResource:
        @limiter.rate_limit(requests=2, per=relativedelta(seconds=1))
        async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.status = falcon.HTTP_200
            resp.text = "ASYNC DECORATED OK"

    app = falcon.asgi.App(middleware=cast(list[Any], [middleware]))
    app.add_route("/async-middleware-test", AsyncMiddlewareProtectedResource())
    app.add_route("/async-middleware-decorated", AsyncDecoratedResource())
    return app
