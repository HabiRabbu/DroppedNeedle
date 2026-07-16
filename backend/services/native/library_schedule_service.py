"""Terminal-time scheduling for target filesystem scans."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

_INTERVALS = {
    "5min": timedelta(minutes=5),
    "10min": timedelta(minutes=10),
    "30min": timedelta(minutes=30),
    "1hr": timedelta(hours=1),
    "6hr": timedelta(hours=6),
    "12hr": timedelta(hours=12),
    "24hr": timedelta(hours=24),
    "3d": timedelta(days=3),
    "7d": timedelta(days=7),
}


class LibraryScheduleService:
    @staticmethod
    def next_due(
        frequency: str,
        daily_time: str,
        terminal_at: float | None,
        *,
        now: datetime,
        timezone_name: str,
    ) -> datetime | None:
        if frequency == "manual":
            return None
        zone = ZoneInfo(timezone_name)
        local_now = now.astimezone(zone)
        if frequency != "daily":
            interval = _INTERVALS.get(frequency)
            if interval is None:
                return None
            if terminal_at is None:
                return local_now
            return datetime.fromtimestamp(terminal_at, zone) + interval
        try:
            hour, minute = (int(part) for part in daily_time.split(":", 1))
            if not 0 <= hour <= 23 or not 0 <= minute <= 59:
                raise ValueError
        except (TypeError, ValueError):
            hour, minute = 3, 0
        if terminal_at is None:
            today = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return today if local_now < today else local_now
        terminal = datetime.fromtimestamp(terminal_at, zone)
        next_day = terminal.date() + timedelta(days=1)
        candidate = datetime(
            next_day.year,
            next_day.month,
            next_day.day,
            hour,
            minute,
            tzinfo=zone,
        )
        round_trip = candidate.astimezone(UTC).astimezone(zone)
        if (round_trip.hour, round_trip.minute) != (hour, minute):
            return round_trip
        return candidate

    @classmethod
    def seconds_until_due(
        cls,
        frequency: str,
        daily_time: str,
        terminal_at: float | None,
        *,
        now: datetime,
        timezone_name: str,
    ) -> float | None:
        due = cls.next_due(
            frequency,
            daily_time,
            terminal_at,
            now=now,
            timezone_name=timezone_name,
        )
        return (
            None
            if due is None
            else max(0.0, (due - now.astimezone(due.tzinfo)).total_seconds())
        )
