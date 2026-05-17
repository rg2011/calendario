from collections.abc import Callable
from datetime import date, datetime, timezone
from functools import wraps
from hashlib import sha256
from typing import Any

from flask import make_response, request


class HttpCacheState:
    """Mantiene versiones en memoria para revalidación HTTP condicional."""

    def __init__(self) -> None:
        boot_time = self._now()
        self._versions = {
            'app': boot_time,
            'data': boot_time,
            'holidays': boot_time,
        }

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _local_now(self) -> datetime:
        return datetime.now().astimezone()

    def touch(self, *names: str) -> None:
        current_time = self._now()
        for name in names:
            self._versions[name] = current_time

    def touch_data(self) -> None:
        self.touch('data')

    def touch_holidays(self) -> None:
        self.touch('holidays')

    def current_day_snapshot(self) -> tuple[str, datetime]:
        local_now = self._local_now()
        local_day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        return local_now.date().isoformat(), local_day_start.astimezone(timezone.utc)

    def last_modified(self, *names: str, floor: datetime | None = None) -> datetime:
        version_names = names or ('app',)
        current_last_modified = max(self._versions[name] for name in version_names)
        if floor is not None and floor > current_last_modified:
            return floor
        return current_last_modified

    def etag_for(
        self,
        resource_key: str,
        *names: str,
        extra_parts: list[str] | None = None,
    ) -> str:
        payload = [str(resource_key)]
        for name in names:
            payload.append(f'{name}={self._versions[name].isoformat(timespec="microseconds")}')
        if extra_parts:
            payload.extend(str(part) for part in extra_parts)
        digest = sha256('|'.join(payload).encode('utf-8')).hexdigest()
        return f'calendario-{digest}'

    def is_not_modified(self, etag: str, last_modified: datetime) -> bool:
        if_none_match = request.headers.get('If-None-Match')
        if if_none_match:
            candidate_tags = {item.strip() for item in if_none_match.split(',') if item.strip()}
            return '*' in candidate_tags or etag in candidate_tags or f'"{etag}"' in candidate_tags

        if_modified_since = request.if_modified_since
        if if_modified_since is not None:
            last_modified_utc = last_modified.astimezone(timezone.utc).replace(microsecond=0)
            if if_modified_since >= last_modified_utc:
                return True

        return False

    def cached_view(
        self,
        resource_builder: Callable[..., str],
        version_names: tuple[str, ...],
        cache_control: str = 'private, no-cache',
        include_current_day: bool = False,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(view_func: Callable[..., Any]) -> Callable[..., Any]:
            @wraps(view_func)
            def wrapped(*args: Any, **kwargs: Any) -> Any:
                resource_key = resource_builder(*args, **kwargs)
                etag_parts = []
                last_modified_floor = None
                if include_current_day:
                    current_day_token, current_day_start = self.current_day_snapshot()
                    etag_parts.append(f'day={current_day_token}')
                    last_modified_floor = current_day_start

                last_modified = self.last_modified(*version_names, floor=last_modified_floor)
                etag = self.etag_for(resource_key, *version_names, extra_parts=etag_parts)

                if self.is_not_modified(etag, last_modified):
                    response = make_response('', 304)
                else:
                    response = make_response(view_func(*args, **kwargs))

                response.set_etag(etag)
                response.last_modified = last_modified
                response.headers['Cache-Control'] = cache_control
                return response

            return wrapped

        return decorator


def calendar_cache_key(year: int, month: int) -> str:
    return f'calendar:{year:04d}-{month:02d}'


def current_month_cache_key() -> str:
    today = date.today()
    return calendar_cache_key(today.year, today.month)


def settings_cache_key() -> str:
    return 'settings'


def absences_cache_key() -> str:
    return 'absences'
