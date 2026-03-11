import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wsgiref.simple_server import make_server
import falcon
from dateutil.relativedelta import relativedelta

from limiter.core import FalconRateLimiter

custom_limiter = FalconRateLimiter()
class ThingsResource:
    @custom_limiter.rate_limit(requests=5, per=relativedelta(minutes=1))  # Example: limit to 5 requests per 60 seconds
    def on_get(self, req, resp):
        """Handles GET requests"""
        resp.status = falcon.HTTP_200  # This is the default status
        resp.content_type = falcon.MEDIA_TEXT  # Default is JSON, so override
        resp.text = ('\nTwo things awe me most, the starry sky '
                     'above me and the moral law within me.\n'
                     '\n'
                     '    ~ Immanuel Kant\n\n')

# falcon.App instances are callable WSGI apps...
# in larger applications the app is created in a separate file
app = falcon.App()
things = ThingsResource()  # Resources are represented by long-lived class instances
# things will handle all requests to the '/things' URL path
app.add_route('/things', things)

if __name__ == '__main__':
    with make_server('', 8000, app) as httpd:
        print('Serving on por'
              't 8000...')

        # Serve until process is killed
        httpd.serve_forever()