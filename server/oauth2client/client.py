# Copyright (C) 2010 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""An OAuth 2.0 client.

Tools for interacting with OAuth 2.0 protected resources.
"""

__author__ = 'jcgregorio@google.com (Joe Gregorio)'

import base64
from . import clientsecrets
import copy
import datetime
import httplib2
import logging
import os
import sys
import time
import urllib.request, urllib.parse, urllib.error
import urllib.parse

from .anyjson import simplejson

HAS_OPENSSL = False
try:
  from oauth2client.crypt import Signer
  from oauth2client.crypt import make_signed_jwt
  from oauth2client.crypt import verify_signed_jwt_with_certs
  HAS_OPENSSL = True
except ImportError:
  pass

try:
  from urllib.parse import parse_qsl
except ImportError:
  from cgi import parse_qsl

logger = logging.getLogger(__name__)

# Expiry is stored in RFC3339 UTC format
EXPIRY_FORMAT = '%Y-%m-%dT%H:%M:%SZ'

# Which certs to use to validate id_tokens received.
ID_TOKEN_VERIFICATON_CERTS = 'https://www.googleapis.com/oauth2/v1/certs'


class Error(Exception):
  """Base error for this module."""
  pass


class FlowExchangeError(Error):
  """Error trying to exchange an authorization grant for an access token."""
  pass


class AccessTokenRefreshError(Error):
  """Error trying to refresh an expired access token."""
  pass

class UnknownClientSecretsFlowError(Error):
  """The client secrets file called for an unknown type of OAuth 2.0 flow. """
  pass


class AccessTokenCredentialsError(Error):
  """Having only the access_token means no refresh is possible."""
  pass


class VerifyJwtTokenError(Error):
  """Could on retrieve certificates for validation."""
  pass


def _abstract():
  raise NotImplementedError('You need to override this function')


class Credentials(object):
  """Base class for all Credentials objects.

  Subclasses must define an authorize() method that applies the credentials to
  an HTTP transport.

  Subclasses must also specify a classmethod named 'from_json' that takes a JSON
  string as input and returns an instaniated Crentials object.
  """

  NON_SERIALIZED_MEMBERS = ['store']

  def authorize(self, http):
    """Take an httplib2.Http instance (or equivalent) and
    authorizes it for the set of credentials, usually by
    replacing http.request() with a method that adds in
    the appropriate headers and then delegates to the original
    Http.request() method.
    """
    _abstract()

  def _to_json(self, strip):
    """Utility function for creating a JSON representation of an instance of Credentials.

    Args:
      strip: array, An array of names of members to not include in the JSON.

    Returns:
       string, a JSON representation of this instance, suitable to pass to
       from_json().
    """
    t = type(self)
    d = copy.copy(self.__dict__)
    for member in strip:
      del d[member]
    if 'token_expiry' in d and isinstance(d['token_expiry'], datetime.datetime):
      d['token_expiry'] = d['token_expiry'].strftime(EXPIRY_FORMAT)
    # Add in information we will need later to reconsistitue this instance.
    d['_class'] = t.__name__
    d['_module'] = t.__module__
    return simplejson.dumps(d)

  def to_json(self):
    """Creating a JSON representation of an instance of Credentials.

    Returns:
       string, a JSON representation of this instance, suitable to pass to
       from_json().
    """
    return self._to_json(Credentials.NON_SERIALIZED_MEMBERS)

  @classmethod
  def new_from_json(cls, s):
    """Utility class method to instantiate a Credentials subclass from a JSON
    representation produced by to_json().

    Args:
      s: string, JSON from to_json().

    Returns:
      An instance of the subclass of Credentials that was serialized with
      to_json().
    """
    data = simplejson.loads(s)
    # Find and call the right classmethod from_json() to restore the object.
    module = data['_module']
    m = __import__(module, fromlist=module.split('.')[:-1])
    kls = getattr(m, data['_class'])
    from_json = getattr(kls, 'from_json')
    return from_json(s)


class Flow(object):
  """Base class for all Flow objects."""
  pass


class Storage(object):
  """Base class for all Storage objects.

  Store and retrieve a single credential.  This class supports locking
  such that multiple processes and threads can operate on a single
  store.
  """

  def acquire_lock(self):
    """Acquires any lock necessary to access this Storage.

    This lock is not reentrant."""
    pass

  def release_lock(self):
    """Release the Storage lock.

    Trying to release a lock that isn't held will result in a
    RuntimeError.
    """
    pass

  def locked_get(self):
    """Retrieve credential.

    The Storage lock must be held when this is called.

    Returns:
      oauth2client.client.Credentials
    """
    _abstract()

  def locked_put(self, credentials):
    """Write a credential.

    The Storage lock must be held when this is called.

    Args:
      credentials: Credentials, the credentials to store.
    """
    _abstract()

  def get(self):
    """Retrieve credential.

    The Storage lock must *not* be held when this is called.

    Returns:
      oauth2client.client.Credentials
    """
    self.acquire_lock()
    try:
      return self.locked_get()
    finally:
      self.release_lock()

  def put(self, credentials):
    """Write a credential.

    The Storage lock must be held when this is called.

    Args:
      credentials: Credentials, the credentials to store.
    """
    self.acquire_lock()
    try:
      self.locked_put(credentials)
    finally:
      self.release_lock()


class OAuth2Credentials(Credentials):
  """Credentials object for OAuth 2.0.

  Credentials can be applied to an httplib2.Http object using the authorize()
  method, which then adds the OAuth 2.0 access token to each request.

  OAuth2Credentials objects may be safely pickled and unpickled.
  """

  def __init__(self, access_token, client_id, client_secret, refresh_token,
               token_expiry, token_uri, user_agent, id_token=None):
    """Create an instance of OAuth2Credentials.

    This constructor is not usually called by the user, instead
    OAuth2Credentials objects are instantiated by the OAuth2WebServerFlow.

    Args:
      access_token: string, access token.
      client_id: string, client identifier.
      client_secret: string, client secret.
      refresh_token: string, refresh token.
      token_expiry: datetime, when the access_token expires.
      token_uri: string, URI of token endpoint.
      user_agent: string, The HTTP User-Agent to provide for this application.
      id_token: object, The identity of the resource owner.

    Notes:
      store: callable, A callable that when passed a Credential
        will store the credential back to where it came from.
        This is needed to store the latest access_token if it
        has expired and been refreshed.
    """
    self.access_token = access_token
    self.client_id = client_id
    self.client_secret = client_secret
    self.refresh_token = refresh_token
    self.store = None
    self.token_expiry = token_expiry
    self.token_uri = token_uri
    self.user_agent = user_agent
    self.id_token = id_token

    # True if the credentials have been revoked or expired and can't be
    # refreshed.
    self.invalid = False

  def to_json(self):
    return self._to_json(Credentials.NON_SERIALIZED_MEMBERS)

  @classmethod
  def from_json(cls, s):
    """Instantiate a Credentials object from a JSON description of it. The JSON
    should have been produced by calling .to_json() on the object.

    Args:
      data: dict, A deserialized JSON object.

    Returns:
      An instance of a Credentials subclass.
    """
    data = simplejson.loads(s)
    if 'token_expiry' in data and not isinstance(data['token_expiry'],
        datetime.datetime):
      try:
        data['token_expiry'] = datetime.datetime.strptime(
            data['token_expiry'], EXPIRY_FORMAT)
      except:
        data['token_expiry'] = None
    retval = OAuth2Credentials(
        data['access_token'],
        data['client_id'],
        data['client_secret'],
        data['refresh_token'],
        data['token_expiry'],
        data['token_uri'],
        data['user_agent'],
        data.get('id_token', None))
    retval.invalid = data['invalid']
    return retval

  @property
  def access_token_expired(self):
    """True if the credential is expired or invalid.

    If the token_expiry isn't set, we assume the token doesn't expire.
    """
    if self.invalid:
      return True

    if not self.token_expiry:
      return False

    now = datetime.datetime.utcnow()
    if now >= self.token_expiry:
      logger.info('access_token is expired. Now: %s, token_expiry: %s',
                  now, self.token_expiry)
      return True
    return False

  def set_store(self, store):
    """Set the Storage for the credential.

    Args:
      store: Storage, an implementation of Stroage object.
        This is needed to store the latest access_token if it
        has expired and been refreshed.  This implementation uses
        locking to check for updates before updating the
        access_token.
    """
    self.store = store

  def _updateFromCredential(self, other):
    """Update this Credential from another instance."""
    self.__dict__.update(other.__getstate__())

  def __getstate__(self):
    """Trim the state down to something that can be pickled."""
    d = copy.copy(self.__dict__)
    del d['store']
    return d

  def __setstate__(self, state):
    """Reconstitute the state of the object from being pickled."""
    self.__dict__.update(state)
    self.store = None

  def _generate_refresh_request_body(self):
    """Generate the body that will be used in the refresh request."""
    body = urllib.parse.urlencode({
        'grant_type': 'refresh_token',
        'client_id': self.client_id,
        'client_secret': self.client_secret,
        'refresh_token': self.refresh_token,
        })
    return body

  def _generate_refresh_request_headers(self):
    """Generate the headers that will be used in the refresh request."""
    headers = {
        'content-type': 'application/x-www-form-urlencoded',
    }

    if self.user_agent is not None:
      headers['user-agent'] = self.user_agent

    return headers

  def _refresh(self, http_request):
    """Refreshes the access_token.

    This method first checks by reading the Storage object if available.
    If a refresh is still needed, it holds the Storage lock until the
    refresh is completed.
    """
    if not self.store:
      self._do_refresh_request(http_request)
    else:
      self.store.acquire_lock()
      try:
        new_cred = self.store.locked_get()
        if (new_cred and not new_cred.invalid and
            new_cred.access_token != self.access_token):
          logger.info('Updated access_token read from Storage')
          self._updateFromCredential(new_cred)
        else:
          self._do_refresh_request(http_request)
      finally:
        self.store.release_lock()

  def _do_refresh_request(self, http_request):
    """Refresh the access_token using the refresh_token.

    Args:
       http: An instance of httplib2.Http.request
           or something that acts like it.

    Raises:
      AccessTokenRefreshError: When the refresh fails.
    """
    body = self._generate_refresh_request_body()
    headers = self._generate_refresh_request_headers()

    logger.info('Refresing access_token')
    resp, content = http_request(
        self.token_uri, method='POST', body=body, headers=headers)
    if resp.status == 200:
      # TODO(jcgregorio) Raise an error if loads fails?
      d = simplejson.loads(content)
      self.access_token = d['access_token']
      self.refresh_token = d.get('refresh_token', self.refresh_token)
      if 'expires_in' in d:
        self.token_expiry = datetime.timedelta(
            seconds=int(d['expires_in'])) + datetime.datetime.utcnow()
      else:
        self.token_expiry = None
      if self.store:
        self.store.locked_put(self)
    else:
      # An {'error':...} response body means the token is expired or revoked,
      # so we flag the credentials as such.
      logger.error('Failed to retrieve access token: %s' % content)
      error_msg = 'Invalid response %s.' % resp['status']
      try:
        d = simplejson.loads(content)
        if 'error' in d:
          error_msg = d['error']
          self.invalid = True
          if self.store:
            self.store.locked_put(self)
      except:
        pass
      raise AccessTokenRefreshError(error_msg)

  def authorize(self, http):
    """Authorize an httplib2.Http instance with these credentials.

    Args:
       http: An instance of httplib2.Http
           or something that acts like it.

    Returns:
       A modified instance of http that was passed in.

    Example:

      h = httplib2.Http()
      h = credentials.authorize(h)

    You can't create a new OAuth subclass of httplib2.Authenication
    because it never gets passed the absolute URI, which is needed for
    signing. So instead we have to overload 'request' with a closure
    that adds in the Authorization header and then calls the original
    version of 'request()'.
    """
    request_orig = http.request

    # The closure that will replace 'httplib2.Http.request'.
    def new_request(uri, method='GET', body=None, headers=None,
                    redirections=httplib2.DEFAULT_MAX_REDIRECTS,
                    connection_type=None):
      if not self.access_token:
        logger.info('Attempting refresh to obtain initial access_token')
        self._refresh(request_orig)

      # Modify the request headers to add the appropriate
      # Authorization header.
      if headers is None:
        headers = {}
      headers['authorization'] = 'OAuth ' + self.access_token

      if self.user_agent is not None:
        if 'user-agent' in headers:
          headers['user-agent'] = self.user_agent + ' ' + headers['user-agent']
        else:
          headers['user-agent'] = self.user_agent

      resp, content = request_orig(uri, method, body, headers,
                                   redirections, connection_type)

      if resp.status == 401:
        logger.info('Refreshing due to a 401')
        self._refresh(request_orig)
        headers['authorization'] = 'OAuth ' + self.access_token
        return request_orig(uri, method, body, headers,
                            redirections, connection_type)
      else:
        return (resp, content)

    http.request = new_request
    return http


class AccessTokenCredentials(OAuth2Credentials):
  """Credentials object for OAuth 2.0.

  Credentials can be applied to an httplib2.Http object using the
  authorize() method, which then signs each request from that object
  with the OAuth 2.0 access token.  This set of credentials is for the
  use case where you have acquired an OAuth 2.0 access_token from
  another place such as a JavaScript client or another web
  application, and wish to use it from Python. Because only the
  access_token is present it can not be refreshed and will in time
  expire.

  AccessTokenCredentials objects may be safely pickled and unpickled.

  Usage:
    credentials = AccessTokenCredentials('<an access token>',
      'my-user-agent/1.0')
    http = httplib2.Http()
    http = credentials.authorize(http)

  Exceptions:
    AccessTokenCredentialsExpired: raised when the access_token expires or is
      revoked.
  """

  def __init__(self, access_token, user_agent):
    """Create an instance of OAuth2Credentials

    This is one of the few types if Credentials that you should contrust,
    Credentials objects are usually instantiated by a Flow.

    Args:
      access_token: string, access token.
      user_agent: string, The HTTP User-Agent to provide for this application.

    Notes:
      store: callable, a callable that when passed a Credential
        will store the credential back to where it came from.
    """
    super(AccessTokenCredentials, self).__init__(
        access_token,
        None,
        None,
        None,
        None,
        None,
        user_agent)


  @classmethod
  def from_json(cls, s):
    data = simplejson.loads(s)
    retval = AccessTokenCredentials(
        data['access_token'],
        data['user_agent'])
    return retval

  def _refresh(self, http_request):
    raise AccessTokenCredentialsError(
        "The access_token is expired or invalid and can't be refreshed.")


class AssertionCredentials(OAuth2Credentials):
  """Abstract Credentials object used for OAuth 2.0 assertion grants.

  This credential does not require a flow to instantiate because it
  represents a two legged flow, and therefore has all of the required
  information to generate and refresh its own access tokens.  It must
  be subclassed to generate the appropriate assertion string.

  AssertionCredentials objects may be safely pickled and unpickled.
  """

  def __init__(self, assertion_type, user_agent,
               token_uri='https://accounts.google.com/o/oauth2/token',
               **unused_kwargs):
    """Constructor for AssertionFlowCredentials.

    Args:
      assertion_type: string, assertion type that will be declared to the auth
          server
      user_agent: string, The HTTP User-Agent to provide for this application.
      token_uri: string, URI for token endpoint. For convenience
        defaults to Google's endpoints but any OAuth 2.0 provider can be used.
    """
    super(AssertionCredentials, self).__init__(
        None,
        None,
        None,
        None,
        None,
        token_uri,
        user_agent)
    self.assertion_type = assertion_type

  def _generate_refresh_request_body(self):
    assertion = self._generate_assertion()

    body = urllib.parse.urlencode({
        'assertion_type': self.assertion_type,
        'assertion': assertion,
        'grant_type': 'assertion',
        })

    return body

  def _generate_assertion(self):
    """Generate the assertion string that will be used in the access token
    request.
    """
    _abstract()

if HAS_OPENSSL:
  # PyOpenSSL is not a prerequisite for oauth2client, so if it is missing then
  # don't create the SignedJwtAssertionCredentials or the verify_id_token()
  # method.

  class SignedJwtAssertionCredentials(AssertionCredentials):
    """Credentials object used for OAuth 2.0 Signed JWT assertion grants.

    This credential does not require a flow to instantiate because it
    represents a two legged flow, and therefore has all of the required
    information to generate and refresh its own access tokens.
    """

    MAX_TOKEN_LIFETIME_SECS = 3600 # 1 hour in seconds

    def __init__(self,
        service_account_name,
        private_key,
        scope,
        private_key_password='notasecret',
        user_agent=None,
        token_uri='https://accounts.google.com/o/oauth2/token',
        **kwargs):
      """Constructor for SignedJwtAssertionCredentials.

      Args:
        service_account_name: string, id for account, usually an email address.
        private_key: string, private key in P12 format.
        scope: string or list of strings, scope(s) of the credentials being
          requested.
        private_key_password: string, password for private_key.
        user_agent: string, HTTP User-Agent to provide for this application.
        token_uri: string, URI for token endpoint. For convenience
          defaults to Google's endpoints but any OAuth 2.0 provider can be used.
        kwargs: kwargs, Additional parameters to add to the JWT token, for
          example prn=joe@xample.org."""

      super(SignedJwtAssertionCredentials, self).__init__(
          'http://oauth.net/grant_type/jwt/1.0/bearer',
          user_agent,
          token_uri=token_uri,
          )

      if type(scope) is list:
        scope = ' '.join(scope)
      self.scope = scope

      self.private_key = private_key
      self.private_key_password = private_key_password
      self.service_account_name = service_account_name
      self.kwargs = kwargs

    @classmethod
    def from_json(cls, s):
      data = simplejson.loads(s)
      retval = SignedJwtAssertionCredentials(
          data['service_account_name'],
          data['private_key'],
          data['private_key_password'],
          data['scope'],
          data['user_agent'],
          data['token_uri'],
          data['kwargs']
          )
      retval.invalid = data['invalid']
      return retval

    def _generate_assertion(self):
      """Generate the assertion that will be used in the request."""
      now = int(time.time())
      payload = {
          'aud': self.token_uri,
          'scope': self.scope,
          'iat': now,
          'exp': now + SignedJwtAssertionCredentials.MAX_TOKEN_LIFETIME_SECS,
          'iss': self.service_account_name
      }
      payload.update(self.kwargs)
      logging.debug(str(payload))

      return make_signed_jwt(
          Signer.from_string(self.private_key, self.private_key_password),
          payload)


  def verify_id_token(id_token, audience, http=None,
      cert_uri=ID_TOKEN_VERIFICATON_CERTS):
    """Verifies a signed JWT id_token.

    Args:
      id_token: string, A Signed JWT.
      audience: string, The audience 'aud' that the token should be for.
      http: httplib2.Http, instance to use to make the HTTP request. Callers
        should supply an instance that has caching enabled.
      cert_uri: string, URI of the certificates in JSON format to
        verify the JWT against.

    Returns:
      The deserialized JSON in the JWT.

    Raises:
      oauth2client.crypt.AppIdentityError if the JWT fails to verify.
    """
    if http is None:
      http = httplib2.Http()

    resp, content = http.request(cert_uri)

    if resp.status == 200:
      certs = simplejson.loads(content)
      return verify_signed_jwt_with_certs(id_token, certs, audience)
    else:
      raise VerifyJwtTokenError('Status code: %d' % resp.status)


def _urlsafe_b64decode(b64string):
  # Guard against unicode strings, which base64 can't handle.
  b64string = b64string.encode('ascii')
  padded = b64string + '=' * (4 - len(b64string) % 4)
  return base64.urlsafe_b64decode(padded)


def _extract_id_token(id_token):
  """Extract the JSON payload from a JWT.

  Does the extraction w/o checking the signature.

  Args:
    id_token: string, OAuth 2.0 id_token.

  Returns:
    object, The deserialized JSON payload.
  """
  segments = id_token.split('.')

  if (len(segments) != 3):
    raise VerifyJwtTokenError(
      'Wrong number of segments in token: %s' % id_token)

  return simplejson.loads(_urlsafe_b64decode(segments[1]))


class OAuth2WebServerFlow(Flow):
  """Does the Web Server Flow for OAuth 2.0.

  OAuth2Credentials objects may be safely pickled and unpickled.
  """

  def __init__(self, client_id, client_secret, scope, user_agent=None,
               auth_uri='https://accounts.google.com/o/oauth2/auth',
               token_uri='https://accounts.google.com/o/oauth2/token',
               **kwargs):
    """Constructor for OAuth2WebServerFlow.

    Args:
      client_id: string, client identifier.
      client_secret: string client secret.
      scope: string or list of strings, scope(s) of the credentials being
        requested.
      user_agent: string, HTTP User-Agent to provide for this application.
      auth_uri: string, URI for authorization endpoint. For convenience
        defaults to Google's endpoints but any OAuth 2.0 provider can be used.
      token_uri: string, URI for token endpoint. For convenience
        defaults to Google's endpoints but any OAuth 2.0 provider can be used.
      **kwargs: dict, The keyword arguments are all optional and required
                        parameters for the OAuth calls.
    """
    self.client_id = client_id
    self.client_secret = client_secret
    if type(scope) is list:
      scope = ' '.join(scope)
    self.scope = scope
    self.user_agent = user_agent
    self.auth_uri = auth_uri
    self.token_uri = token_uri
    self.params = {
        'access_type': 'offline',
        }
    self.params.update(kwargs)
    self.redirect_uri = None

  def step1_get_authorize_url(self, redirect_uri='oob'):
    """Returns a URI to redirect to the provider.

    Args:
      redirect_uri: string, Either the string 'oob' for a non-web-based
                    application, or a URI that handles the callback from
                    the authorization server.

    If redirect_uri is 'oob' then pass in the
    generated verification code to step2_exchange,
    otherwise pass in the query parameters received
    at the callback uri to step2_exchange.
    """

    self.redirect_uri = redirect_uri
    query = {
        'response_type': 'code',
        'client_id': self.client_id,
        'redirect_uri': redirect_uri,
        'scope': self.scope,
        }
    query.update(self.params)
    parts = list(urllib.parse.urlparse(self.auth_uri))
    query.update(dict(parse_qsl(parts[4]))) # 4 is the index of the query part
    parts[4] = urllib.parse.urlencode(query)
    return urllib.parse.urlunparse(parts)

  def step2_exchange(self, code, http=None):
    """Exhanges a code for OAuth2Credentials.

    Args:
      code: string or dict, either the code as a string, or a dictionary
        of the query parameters to the redirect_uri, which contains
        the code.
      http: httplib2.Http, optional http instance to use to do the fetch
    """

    if not (isinstance(code, str) or isinstance(code, str)):
      code = code['code']

    body = urllib.parse.urlencode({
        'grant_type': 'authorization_code',
        'client_id': self.client_id,
        'client_secret': self.client_secret,
        'code': code,
        'redirect_uri': self.redirect_uri,
        'scope': self.scope,
        })
    headers = {
        'content-type': 'application/x-www-form-urlencoded',
    }

    if self.user_agent is not None:
      headers['user-agent'] = self.user_agent

    if http is None:
      http = httplib2.Http()

    resp, content = http.request(self.token_uri, method='POST', body=body,
                                 headers=headers)
    if resp.status == 200:
      # TODO(jcgregorio) Raise an error if simplejson.loads fails?
      d = simplejson.loads(content)
      access_token = d['access_token']
      refresh_token = d.get('refresh_token', None)
      token_expiry = None
      if 'expires_in' in d:
        token_expiry = datetime.datetime.utcnow() + datetime.timedelta(
            seconds=int(d['expires_in']))

      if 'id_token' in d:
        d['id_token'] = _extract_id_token(d['id_token'])

      logger.info('Successfully retrieved access token: %s' % content)
      return OAuth2Credentials(access_token, self.client_id,
                               self.client_secret, refresh_token, token_expiry,
                               self.token_uri, self.user_agent,
                               id_token=d.get('id_token', None))
    else:
      logger.error('Failed to retrieve access token: %s' % content)
      error_msg = 'Invalid response %s.' % resp['status']
      try:
        d = simplejson.loads(content)
        if 'error' in d:
          error_msg = d['error']
      except:
        pass

      raise FlowExchangeError(error_msg)

def flow_from_clientsecrets(filename, scope, message=None):
  """Create a Flow from a clientsecrets file.

  Will create the right kind of Flow based on the contents of the clientsecrets
  file or will raise InvalidClientSecretsError for unknown types of Flows.

  Args:
    filename: string, File name of client secrets.
    scope: string or list of strings, scope(s) to request.
    message: string, A friendly string to display to the user if the
      clientsecrets file is missing or invalid. If message is provided then
      sys.exit will be called in the case of an error. If message in not
      provided then clientsecrets.InvalidClientSecretsError will be raised.

  Returns:
    A Flow object.

  Raises:
    UnknownClientSecretsFlowError if the file describes an unknown kind of Flow.
    clientsecrets.InvalidClientSecretsError if the clientsecrets file is
      invalid.
  """
  try:
    client_type, client_info = clientsecrets.loadfile(filename)
    if client_type in [clientsecrets.TYPE_WEB, clientsecrets.TYPE_INSTALLED]:
        return OAuth2WebServerFlow(
            client_info['client_id'],
            client_info['client_secret'],
            scope,
            None, # user_agent
            client_info['auth_uri'],
            client_info['token_uri'])
  except clientsecrets.InvalidClientSecretsError:
    if message:
      sys.exit(message)
    else:
      raise
  else:
    raise UnknownClientSecretsFlowError(
        'This OAuth 2.0 flow is unsupported: "%s"' * client_type)
