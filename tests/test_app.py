import falcon
import falcon.asgi
from dateutil.relativedelta import relativedelta
from typing import Any, cast

from limiter import FalconRateLimitMiddleware, FalconRateLimiter


def create_app() -> falcon.App:
    limiter = FalconRateLimiter()

    def client_key(req: falcon.Request) -> str:
        return req.get_header("X-Client-Id") or req.remote_addr or "global"

    def internal_request(req: falcon.Request) -> bool:
        return req.get_header("X-Internal") == "true"

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

    class MethodFilteredResource:
        @limiter.rate_limit(
            requests=1,
            per=relativedelta(seconds=1),
            methods=["POST"],
        )
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.status = falcon.HTTP_200
            resp.text = "METHOD FILTER GET OK"

        @limiter.rate_limit(
            requests=1,
            per=relativedelta(seconds=1),
            methods=["POST"],
        )
        def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.status = falcon.HTTP_200
            resp.text = "METHOD FILTER POST OK"

    class PerMethodResource:
        @limiter.rate_limit(
            requests=1,
            per=relativedelta(seconds=1),
            per_method=True,
        )
        def handle(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.status = falcon.HTTP_200
            resp.text = "PER METHOD OK"

        on_get = handle
        on_post = handle

    class ConditionalExemptResource:
        @limiter.rate_limit(
            requests=1,
            per=relativedelta(seconds=1),
            exempt_when=internal_request,
        )
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.status = falcon.HTTP_200
            resp.text = "CONDITIONAL EXEMPT OK"

    class ExemptDecoratedResource:
        @limiter.exempt
        @limiter.rate_limit(
            requests=1,
            per=relativedelta(seconds=1),
        )
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.status = falcon.HTTP_200
            resp.text = "EXEMPT OK"

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
    app.add_route("/method-filtered", MethodFilteredResource())
    app.add_route("/per-method", PerMethodResource())
    app.add_route("/conditional-exempt", ConditionalExemptResource())
    app.add_route("/exempt-decorated", ExemptDecoratedResource())
    app.add_route("/class-test", ClassDecoratedResource())
    app.add_route("/class-per-client", ClassPerClientResource())
    return app


def create_async_app() -> falcon.asgi.App:
    limiter = FalconRateLimiter()

    def client_key(req: falcon.Request) -> str:
        return req.get_header("X-Client-Id") or req.remote_addr or "global"

    def internal_request(req: falcon.Request) -> bool:
        return req.get_header("X-Internal") == "true"

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

    class AsyncMethodFilteredResource:
        @limiter.rate_limit(
            requests=1,
            per=relativedelta(seconds=1),
            methods=["POST"],
        )
        async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.status = falcon.HTTP_200
            resp.text = "ASYNC METHOD FILTER GET OK"

        @limiter.rate_limit(
            requests=1,
            per=relativedelta(seconds=1),
            methods=["POST"],
        )
        async def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.status = falcon.HTTP_200
            resp.text = "ASYNC METHOD FILTER POST OK"

    class AsyncPerMethodResource:
        @limiter.rate_limit(
            requests=1,
            per=relativedelta(seconds=1),
            per_method=True,
        )
        async def handle(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.status = falcon.HTTP_200
            resp.text = "ASYNC PER METHOD OK"

        on_get = handle
        on_post = handle

    class AsyncConditionalExemptResource:
        @limiter.rate_limit(
            requests=1,
            per=relativedelta(seconds=1),
            exempt_when=internal_request,
        )
        async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.status = falcon.HTTP_200
            resp.text = "ASYNC CONDITIONAL EXEMPT OK"

    class AsyncExemptDecoratedResource:
        @limiter.exempt
        @limiter.rate_limit(requests=1, per=relativedelta(seconds=1))
        async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.status = falcon.HTTP_200
            resp.text = "ASYNC EXEMPT OK"

    @limiter.rate_limit(requests=2, per=relativedelta(seconds=1))
    class AsyncClassDecoratedResource:
        async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.status = falcon.HTTP_200
            resp.text = "ASYNC CLASS OK"

    app = falcon.asgi.App()
    app.add_route("/async-test", AsyncTestResource())
    app.add_route("/async-per-client", AsyncPerClientResource())
    app.add_route("/async-custom-message", AsyncCustomMessageResource())
    app.add_route("/async-method-filtered", AsyncMethodFilteredResource())
    app.add_route("/async-per-method", AsyncPerMethodResource())
    app.add_route("/async-conditional-exempt", AsyncConditionalExemptResource())
    app.add_route("/async-exempt-decorated", AsyncExemptDecoratedResource())
    app.add_route("/async-class-test", AsyncClassDecoratedResource())
    return app


def create_middleware_app(
    limit_undecorated_routes: bool = True,
    default_requests: int | None = None,
    default_per: relativedelta | None = None,
) -> falcon.App:
    limiter = FalconRateLimiter(
        limit_undecorated_routes=limit_undecorated_routes,
        default_requests=default_requests,
        default_per=default_per,
    )
    if default_requests is None and default_per is None:
        middleware = FalconRateLimitMiddleware(
            limiter,
            requests=1,
            per=relativedelta(seconds=1),
        )
    else:
        middleware = FalconRateLimitMiddleware(limiter)

    class MiddlewareProtectedResource:
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.status = falcon.HTTP_200
            resp.text = "MIDDLEWARE OK"

    class DecoratedResource:
        @limiter.rate_limit(requests=2, per=relativedelta(seconds=1))
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.status = falcon.HTTP_200
            resp.text = "DECORATED OK"

    class DefaultLimitedResource:
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.status = falcon.HTTP_200
            resp.text = "DEFAULT OK"

    @limiter.exempt
    class ExemptDefaultResource:
        def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.status = falcon.HTTP_200
            resp.text = "EXEMPT DEFAULT OK"

    app = falcon.App(middleware=[middleware])
    app.add_route("/middleware-test", MiddlewareProtectedResource())
    app.add_route("/middleware-decorated", DecoratedResource())
    app.add_route("/middleware-default", DefaultLimitedResource())
    app.add_route("/middleware-exempt", ExemptDefaultResource())
    return app


def create_async_middleware_app(
    limit_undecorated_routes: bool = True,
    default_requests: int | None = None,
    default_per: relativedelta | None = None,
) -> falcon.asgi.App:
    limiter = FalconRateLimiter(
        limit_undecorated_routes=limit_undecorated_routes,
        default_requests=default_requests,
        default_per=default_per,
    )
    if default_requests is None and default_per is None:
        middleware = FalconRateLimitMiddleware(
            limiter,
            requests=1,
            per=relativedelta(seconds=1),
        )
    else:
        middleware = FalconRateLimitMiddleware(limiter)

    class AsyncMiddlewareProtectedResource:
        async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.status = falcon.HTTP_200
            resp.text = "ASYNC MIDDLEWARE OK"

    class AsyncDecoratedResource:
        @limiter.rate_limit(requests=2, per=relativedelta(seconds=1))
        async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.status = falcon.HTTP_200
            resp.text = "ASYNC DECORATED OK"

    class AsyncDefaultLimitedResource:
        async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.status = falcon.HTTP_200
            resp.text = "ASYNC DEFAULT OK"

    @limiter.exempt
    class AsyncExemptDefaultResource:
        async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
            resp.status = falcon.HTTP_200
            resp.text = "ASYNC EXEMPT DEFAULT OK"

    app = falcon.asgi.App(middleware=cast(list[Any], [middleware]))
    app.add_route("/async-middleware-test", AsyncMiddlewareProtectedResource())
    app.add_route("/async-middleware-decorated", AsyncDecoratedResource())
    app.add_route("/async-middleware-default", AsyncDefaultLimitedResource())
    app.add_route("/async-middleware-exempt", AsyncExemptDefaultResource())
    return app
