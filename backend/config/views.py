"""Serves the built React app and uploaded files from the same port as the API.

The shop runs one Windows machine with no reverse proxy, so Django has to hand
out the single-page app itself: any path that is not an API, admin or media route
belongs to the React router and gets the same shell back.
"""
import mimetypes
import pathlib

from django.conf import settings
from django.http import FileResponse, HttpResponse, HttpResponseNotFound, JsonResponse


def spa_index(request, *args, **kwargs):
    index = pathlib.Path(settings.FRONTEND_DIST) / 'index.html'
    if not index.exists():
        return HttpResponseNotFound(
            "The shop app has not been built yet. Run `npm run build` inside "
            "the frontend folder, then reload this page."
        )
    response = HttpResponse(index.read_bytes(), content_type='text/html; charset=utf-8')
    # The shell must never be cached, or an updated build would keep loading the
    # old hashed bundles referenced by the stale HTML.
    response['Cache-Control'] = 'no-store'
    return response


def media_file(request, relpath):
    root = pathlib.Path(settings.MEDIA_ROOT).resolve()
    target = (root / relpath).resolve()
    # A resolved path that escapes the media root means the caller walked up with
    # "..", which must never read outside the upload folder.
    if not target.is_relative_to(root) or not target.is_file():
        return JsonResponse({'detail': 'Not found.'}, status=404)
    content_type = mimetypes.guess_type(str(target))[0] or 'application/octet-stream'
    return FileResponse(target.open('rb'), content_type=content_type)
