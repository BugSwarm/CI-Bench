import copy
import time
from collections import deque
from typing import List, Literal, Optional, Tuple
from urllib.parse import urlparse

import cachecontrol
import requests

from bugswarm.common import log
from sweagent.utils.log import get_logger

logger = get_logger("env_utils")


class GitHubWrapper(object):
    """
    Wrapper around the GitHub API. This wraper is not meant to implement convenience methods to access GitHub API
    endpoints. Instead, its goals are to facilitate:
    - automatically retrying when a GitHub request fails
    - automatically choosing another available GitHub token when the current token's quota is exceeded
    - automatically waiting until any token's quota is reset when all tokens exceeded their quota.
    """

    def __init__(self, token: str):
        """
        :param tokens: A list of GitHub tokens.
        """
        if not isinstance(token, str):
            raise TypeError('Token must be a string.')

        self._token = token
        self._session = cachecontrol.CacheControl(requests.Session())
        # Start with the first token. We lazily switch tokens as each hits its quota limit.
        self._session.headers['Authorization'] = 'token %s' % self._token

    def get(self, url: str, response_format: Literal['json', 'text', 'bytes'] = 'json', max_retry: int = 5):
        """
        Request a URL from the GitHub API.
        Handles retrying, waiting for quota to reset, and token switching.

        :param url: The GitHub API URL to request.
        :return: A 2-tuple of the resulting response and the JSON representation of the response body. If there was a
                 problem, the returned tuple is (None, None).
        """

        if not isinstance(url, str):
            raise TypeError('The provided URL must be a string.')
        if response_format not in ['json', 'text', 'bytes']:
            raise ValueError('The response format must be one of "json", "text", or "bytes".')
        if urlparse(url).netloc != 'api.github.com':
            raise ValueError('The provided URL is not for the GitHub API.')

        retry_back_off = 5  # Seconds.
        retry_count = 0
        while True:
            response = None
            try:
                response = self._session.get(url)
                response.raise_for_status()

                if response_format == 'json':
                    if not response.text:
                        return response, None
                    return response, response.json()

                if response_format == 'text':
                    return response, response.text

                if response_format == 'bytes':
                    return response, response.content
            except Exception as e:
                # If the exception is a connection error, the server may have dropped the connection.
                # In this case, we should try resetting the session.
                # if e is requests.ConnectionError:
                #    logger.info('Recreating session.')
                #    self._create_session()

                if response.status_code == 404:  # Not found
                    logger.error('URL not found:', url)
                    return response, None
                elif response.status_code == 451:  # Repository access blocked.
                    logger.error('Repository access blocked:', url)
                    return response, None
                elif response.status_code == 401:  # Not authorized.
                    logger.error('Invalid GitHub API token: ', self._session.headers['Authorization'])
                    return response, None
                elif response.status_code == 422:  # Unprocessable Content
                    return response, None
                elif response.status_code == 410:  # Gone (e.g. expired logs)
                    return response, None
                else:
                    logger.error('Request for url failed:', url)
                    logger.error('Exception:', e)
                    # if retry_count >= max_retry:
                    #    logger.error('Stop retrying after {} retry failures'.format(retry_count))
                    #    return response, None

                # If the status code is 403 (Forbidden), then we may have exceeded our GitHub API quota.
                # In this case, we should verify that the quota was exceeded and, if so, wait until the quota is reset.
                if response is not None and response.status_code == 403:
                    result = response.json()
                    # Check whether GitHub's abuse detection mechanism was triggered.
                    if 'Retry-After' in response.headers:
                        retry_after = int(response.headers['Retry-After'])
                        logger.warning(
                            "Triggered GitHub's secondary rate limit. Sleeping for {} seconds.".format(retry_after))
                        time.sleep(retry_after)
                    else:
                        quota_exceeded, sleep_duration = self._exceeded_api_quota()
                        if quota_exceeded:
                            # Pick another token.
                            # self._create_session()
                            logger.error('GitHub API quota exceeded, Add a new github token')
                        else:
                            logger.error('GitHub API quota not exceeded, but 403 error encountered.')
                            logger.error('Headers: {}'.format(response.headers))
                            logger.error('Result: {}'.format(result))

                time.sleep(retry_back_off)
                retry_back_off *= 2
                retry_count += 1

    def get_all_pages(self, url: str):
        """
        Request a URL from the GitHub API that requires pagination.
        Handles retrying, waiting for quota to reset, and token switching.

        :param url: The GitHub API URL to request. Should require pagination.
        :return: The concatenated results of all pages of results for `url`.
        """
        if not isinstance(url, str):
            raise TypeError('The provided URL must be a string.')

        all_results = []
        while True:
            response, result = self.get(url)
            if None in (response, result):
                break
            all_results = sum([result], all_results)
            next_reference = response.links.get('next')
            if next_reference is None:
                break
            url = next_reference.get('url')
        return all_results

    def _exceeded_api_quota(self) -> Tuple[bool, Optional[int]]:
        """
        :return: A 2-tuple. (True, number of seconds until the quota resets) if the API quota has been exceeded.
                 (False, None) otherwise.
        :raises Exception: When an exception is raised by the request.
        """
        quota_url = 'https://api.github.com/rate_limit'
        logger.info('Checking GitHub API quota.')
        response = self._session.get(quota_url)
        try:
            response.raise_for_status()
            result = response.json()
            if 'resources' in result:
                remaining = result['resources']['core']['remaining']
                if remaining <= 0:
                    reset_at = result['resources']['core']['reset']  # Time when the quota resets, in UTC epoch seconds
                    logger.warning('GitHub API quota exceeded and will reset at UTC {}.'.format(reset_at))
                    now = int(time.time())
                    sleep_duration = (reset_at - now) + 10  # Add a few seconds to be sure that we sleep long enough.
                    return True, sleep_duration
        except Exception as e:
            logger.error('Exception while checking API quota:', e)
            raise
        return False, None

    '''
    def _create_session(self):
        """
        When the quota is exceeded for a token, the program will switch to another tokens and attempt to continue.
        If the quota is exceeded for all tokens, the program will wait for the token with the lowest wait time.
        """
        min_wait_time = 9999
        chosen_token = None
        updated_token = copy.deepcopy(self._token)
        for t in self._tokens:
            self._session = cachecontrol.CacheControl(requests.Session())
            self._session.headers['Authorization'] = 'token %s' % t
            has_wait, wait_time = self._exceeded_api_quota()
            if not has_wait:
                chosen_token = t
                min_wait_time = 0
                # if a token is chosen, move it to the end
                updated_token.append(t)
                del updated_token[updated_token.index(t)]
                break
            if wait_time < min_wait_time:
                min_wait_time = wait_time
                chosen_token = t
                # if a token is chosen, move it to the end
                updated_token.append(t)
                del updated_token[updated_token.index(t)]
        self._tokens = updated_token
        if not chosen_token:
            raise RuntimeError('Unexpected state: No GitHub token chosen in github.py.')
        logger.debug('Chose token {}.'.format(chosen_token))
        if min_wait_time:
            # Sleep until the quota is reset. See https://developer.github.com/v3/#rate-limiting for more information.
            logger.warning('Sleeping until the GitHub API quota is reset in', min_wait_time / 60, 'minutes.')
            time.sleep(min_wait_time)
        self._session = cachecontrol.CacheControl(requests.Session())
        self._session.headers['Authorization'] = 'token %s' % chosen_token
    '''