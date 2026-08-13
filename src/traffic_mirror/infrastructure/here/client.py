"""HTTP communication with HERE, isolated from traffic-domain parsing."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol


class HereApiError(RuntimeError):
    """A sanitized HERE boundary failure safe to display or log."""


class JsonTransport(Protocol):
    def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, str],
        timeout_seconds: float,
    ) -> dict[str, Any]: ...


class RequestsJsonTransport:
    """Requests implementation imported only when an HTTP call is made."""

    def __init__(self, session: object | None = None) -> None:
        self._session = session

    def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, str],
        timeout_seconds: float,
    ) -> dict[str, Any]:
        try:
            import requests
        except ImportError as error:  # pragma: no cover - installation error
            raise HereApiError(
                "The 'requests' package is required for live HERE access."
            ) from error

        requester: Any = self._session or requests.Session()
        try:
            response = requester.get(url, params=dict(params), timeout=timeout_seconds)
            response.raise_for_status()
            payload = response.json()
        except requests.Timeout as error:
            raise HereApiError(
                f"HERE request timed out after {timeout_seconds:g} seconds."
            ) from error
        except requests.HTTPError as error:
            status_code = getattr(getattr(error, "response", None), "status_code", None)
            suffix = f" (HTTP {status_code})" if status_code is not None else ""
            # Deliberately do not interpolate the requests exception: its URL can
            # contain the apiKey query parameter.
            raise HereApiError(f"HERE rejected the request{suffix}.") from error
        except requests.RequestException as error:
            raise HereApiError("HERE request failed due to a network error.") from error
        except ValueError as error:
            raise HereApiError("HERE returned malformed JSON.") from error

        if not isinstance(payload, dict):
            raise HereApiError("HERE returned JSON with an unexpected top-level type.")
        return payload


class HereEndpointFetcher:
    def __init__(
        self,
        *,
        transport: JsonTransport,
        api_key: str,
        bbox: str,
        url: str,
        timeout_seconds: float = 10.0,
        use_deep_coverage: bool = False,
    ) -> None:
        if not api_key:
            raise HereApiError("HERE_API_KEY is empty. Configure it in .env before live access.")
        self._transport = transport
        self._api_key = api_key
        self._bbox = bbox
        self._url = url
        self._timeout_seconds = timeout_seconds
        self._use_deep_coverage = use_deep_coverage

    def fetch(self) -> dict[str, Any]:
        params = {
            "apiKey": self._api_key,
            "in": self._bbox,
            "locationReferencing": "shape",
        }
        if self._use_deep_coverage:
            params["advancedFeatures"] = "deepCoverage"
        return self._transport.get_json(
            self._url,
            params=params,
            timeout_seconds=self._timeout_seconds,
        )
