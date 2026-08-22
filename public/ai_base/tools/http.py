# -*- coding: utf-8 -*-
"""HTTP helpers shared by every vendor provider client."""

import requests

from odoo import _


class AiError(Exception):
    """Raised when a vendor call cannot be completed."""


def normalize_base_url(url):
    """Ensure the endpoint carries an explicit http/https scheme."""
    url = (url or '').strip().rstrip('/')
    if not url:
        return url
    if '://' not in url:
        return 'http://' + url
    return url


def _http_error_message(url, status, body):
    message = _('The API returned HTTP error %s: %s') % (status, (body or '')[:500])
    if status == 404 and str(url).rstrip('/').endswith('/models'):
        message = '%s %s' % (message, _(
            'The model list endpoint was not found. For llama.cpp / vLLM, '
            'set the endpoint to http://<host>:<port>/v1 so that '
            '/v1/models is used.'))
    return message


def _request_error_message(url, exc):
    text = str(exc)
    if 'No connection adapters were found' in text:
        return _(
            'The endpoint is missing a scheme: "%s". Add http:// or https://.') % url
    if isinstance(exc, requests.ConnectionError):
        return _('Could not connect to "%s". Check the address and that the '
                 'service is running.') % url
    if isinstance(exc, requests.Timeout):
        return _('The request to "%s" timed out.') % url
    return _('Request failed: %s') % text


def http_request(method, url, timeout=60, proxies=None, **kwargs):
    """Synchronous JSON HTTP helper used by every provider client (and tests)."""
    try:
        resp = requests.request(
            method, url, timeout=timeout or 60, proxies=proxies, **kwargs)
    except requests.RequestException as exc:
        raise AiError(_request_error_message(url, exc)) from exc
    if resp.status_code >= 400:
        raise AiError(_http_error_message(url, resp.status_code, resp.text))
    resp.encoding = 'utf-8'
    try:
        return resp.json()
    except ValueError as exc:
        raise AiError(_('The API returned non-JSON data: %s') % (
            resp.text[:500])) from exc


def http_stream(method, url, timeout=120, proxies=None, **kwargs):
    try:
        resp = requests.request(
            method, url, stream=True, timeout=timeout or 120,
            proxies=proxies, **kwargs)
    except requests.RequestException as exc:
        raise AiError(_request_error_message(url, exc)) from exc
    if resp.status_code >= 400:
        raise AiError(_http_error_message(url, resp.status_code, resp.text))
    resp.encoding = 'utf-8'
    return resp
