import os
import sys
import logging
import time
import datetime
import click
import jinja2
import werkzeug.serving
from whitenoise import WhiteNoise
from werkzeug.debug import DebuggedApplication
from werkzeug.middleware.shared_data import SharedDataMiddleware
from werkzeug.serving import run_simple
from webob.dec import wsgify
from webob import Response, exc
from funcy import memoize, cache
from pathlib import Path
from environs import Env

from google_auth_oauthlib.flow import Flow
import googleapiclient.discovery
import google.oauth2.credentials

os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

logger = logging.getLogger(__name__)
env = Env()
env.read_env()
# ------- initialization -------


templates_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(
        [os.path.join(os.path.dirname(__file__), "templates")]
    ),
    autoescape=jinja2.select_autoescape(["html", "xml"]),
)

def credentials_to_dict(credentials):
  return {'token': credentials.token,
          'refresh_token': credentials.refresh_token,
          'token_uri': credentials.token_uri,
          'client_id': credentials.client_id,
          'client_secret': credentials.client_secret,
          'scopes': credentials.scopes}

# @memoize
def get_template(template_name):
    return templates_env.get_template(template_name)


# @cache(60 * 60)
def home(req):
    return get_template('home.html').render(current_year=datetime.datetime.now().year)



def oauth2_request(req):
    # meat is here: https://developers.google.com/identity/protocols/oauth2/web-server#python

    flow = Flow.from_client_config(
        client_config={
              "web": {
                  "client_id": env("OAUTH_CLIENT_ID"),
                  "client_secret": env("OAUTH_CLIENT_SECRET"),
                  # "callbackUrl": "http://localhost:8000",
                  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                  "token_uri": "https://accounts.google.com/o/oauth2/token"
              }
        },
        scopes=["https://www.googleapis.com/auth/fitness.activity.read"])

    flow.redirect_uri = "http://localhost:8000/oauth2callback/"

    auth_url, _ = flow.authorization_url(
        prompt='consent',
        access_type='offline',
        include_granted_scopes='true')

    return Response(status=302, location=auth_url)


def oauth2_callback(req):

    flow = Flow.from_client_config(
        client_config={
              "web": {
                  "client_id": env("OAUTH_CLIENT_ID"),
                  "client_secret": env("OAUTH_CLIENT_SECRET"),
                  # "callbackUrl": "http://localhost:8000",
                  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                  "token_uri": "https://accounts.google.com/o/oauth2/token"
              }
        },
        scopes=["https://www.googleapis.com/auth/fitness.activity.read"],
        state=req.GET['state'])

    flow.redirect_uri = "http://localhost:8000/oauth2callback/"
    flow.fetch_token(code=req.GET['code'])
    credentials_dict = credentials_to_dict(flow.credentials)


    # The ID is formatted like: "startTime-endTime" where startTime and endTime are
    # 64 bit integers (epoch time with nanoseconds).
    TODAY = datetime.datetime.today().date()
    NOW = datetime.datetime.today()
    START = int(time.mktime(TODAY.timetuple())*1000000000)
    END = int(time.mktime(NOW.timetuple())*1000000000)
    DATA_SET = "%s-%s" % (START, END)
    DATA_SOURCE = "derived:com.google.step_count.delta:com.google.android.gms:estimated_steps"

    credentials = google.oauth2.credentials.Credentials(**credentials_dict)

    fitness_service = googleapiclient.discovery.build('fitness', 'v1', credentials=credentials)

    resp = (fitness_service
            .users()
            .dataSources()
            .datasets()
            .get(userId='me', dataSourceId=DATA_SOURCE, datasetId=DATA_SET)
            .execute())


    total_steps = sum([p['value'][0]['intVal'] for p in resp['point']])
    print("total_steps", total_steps)

    return get_template('approved.html').render(**req.GET)


@wsgify
def application(req):
    if req.path == "/":
        return home(req)
    elif req.path == "/oauth2request/":
        return oauth2_request(req)
    elif req.path == "/oauth2callback/":
        return oauth2_callback(req)
    raise exc.HTTPNotFound


def make_app(use_debugger=False, serve_static=True):
    app =  application
    # if use_debugger:
    #     logger.info("Using Debugger")
    #     app = DebuggedApplication(app)

    if serve_static:
        static_root = os.path.join(os.path.dirname(__file__), "static")
        app = WhiteNoise(app, root=static_root, prefix='static/')

    return app

wsgi_app = make_app()

@click.command()
def cli_runserver():
    host = env("HOST", '0.0.0.0')
    port = env.int("PORT", 8000)
    logger.info(
        "Starting Web Frontend Server on port {}".format(port)
    )



    run_simple(host, port, wsgi_app, use_debugger=True, use_reloader=True)



if __name__ == "__main__":
    cli_runserver()
