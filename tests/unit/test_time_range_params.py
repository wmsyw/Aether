from datetime import date, datetime, timedelta, timezone

import pytest

from src.services.system.time_range import TimeRangeParams, split_time_range_for_hourly


class TestTimeRangeParams:
    # ==================== UTC 转换测试 ====================

    def test_to_utc_datetime_range_with_offset(self) -> None:
        """测试带时区偏移的 UTC 转换"""
        params = TimeRangeParams(
            start_date=date(2026, 2, 1),
            end_date=date(2026, 2, 1),
            tz_offset_minutes=480,  # UTC+8
        )
        start_utc, end_utc = params.to_utc_datetime_range()
        assert start_utc == datetime(2026, 1, 31, 16, 0, tzinfo=timezone.utc)
        assert end_utc == datetime(2026, 2, 1, 16, 0, tzinfo=timezone.utc)

    def test_to_utc_datetime_range_negative_offset(self) -> None:
        """测试负时区偏移（如 UTC-5）"""
        params = TimeRangeParams(
            start_date=date(2026, 2, 1),
            end_date=date(2026, 2, 1),
            tz_offset_minutes=-300,  # UTC-5
        )
        start_utc, end_utc = params.to_utc_datetime_range()
        assert start_utc == datetime(2026, 2, 1, 5, 0, tzinfo=timezone.utc)
        assert end_utc == datetime(2026, 2, 2, 5, 0, tzinfo=timezone.utc)

    def test_to_utc_datetime_range_utc(self) -> None:
        """测试 UTC 时区（无偏移）"""
        params = TimeRangeParams(
            start_date=date(2026, 2, 1),
            end_date=date(2026, 2, 3),
            tz_offset_minutes=0,
        )
        start_utc, end_utc = params.to_utc_datetime_range()
        assert start_utc == datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc)
        assert end_utc == datetime(2026, 2, 4, 0, 0, tzinfo=timezone.utc)  # end_date + 1 day

    # ==================== 预设解析测试 ====================

    def test_preset_today(self) -> None:
        """测试 today 预设"""
        params = TimeRangeParams(preset="today", tz_offset_minutes=0)
        assert params.start_date is not None
        assert params.end_date is not None
        assert params.start_date == params.end_date

    def test_preset_yesterday(self) -> None:
        """测试 yesterday 预设"""
        params = TimeRangeParams(preset="yesterday", tz_offset_minutes=0)
        assert params.start_date is not None
        assert params.end_date is not None
        assert params.start_date == params.end_date
        today_params = TimeRangeParams(preset="today", tz_offset_minutes=0)
        assert today_params.start_date is not None
        assert params.start_date == today_params.start_date - timedelta(days=1)

    def test_preset_last7days(self) -> None:
        """测试 last7days 预设（包含今天共 7 天）"""
        params = TimeRangeParams(preset="last7days", tz_offset_minutes=0)
        assert params.start_date is not None
        assert params.end_date is not None
        days_diff = (params.end_date - params.start_date).days
        assert days_diff == 6  # start 到 end 共 7 天

    def test_preset_last30days(self) -> None:
        """测试 last30days 预设"""
        params = TimeRangeParams(preset="last30days", tz_offset_minutes=0)
        assert params.start_date is not None
        assert params.end_date is not None
        days_diff = (params.end_date - params.start_date).days
        assert days_diff == 29  # start 到 end 共 30 天

    def test_preset_this_month(self) -> None:
        """测试 this_month 预设"""
        params = TimeRangeParams(preset="this_month", tz_offset_minutes=0)
        assert params.start_date is not None
        assert params.end_date is not None
        assert params.start_date.day == 1  # 月初
        assert params.start_date.month == params.end_date.month

    def test_preset_last_month(self) -> None:
        """测试 last_month 预设"""
        params = TimeRangeParams(preset="last_month", tz_offset_minutes=0)
        assert params.start_date is not None
        assert params.end_date is not None
        assert params.start_date.day == 1  # 上月初
        # end_date 应该是上月最后一天
        next_day = params.end_date + timedelta(days=1)
        assert next_day.day == 1  # 下一天是本月初

    # ==================== 跨年/闰年测试 ====================

    def test_cross_year_range(self) -> None:
        """测试跨年日期范围"""
        params = TimeRangeParams(
            start_date=date(2025, 12, 28),
            end_date=date(2026, 1, 3),
            tz_offset_minutes=0,
        )
        assert params.start_date is not None
        assert params.end_date is not None
        start_utc, end_utc = params.to_utc_datetime_range()
        assert start_utc.year == 2025
        assert end_utc.year == 2026
        days = (params.end_date - params.start_date).days + 1
        assert days == 7

    def test_leap_year_february(self) -> None:
        """测试闰年 2 月（2024 是闰年）"""
        params = TimeRangeParams(
            start_date=date(2024, 2, 28),
            end_date=date(2024, 3, 1),
            tz_offset_minutes=0,
        )
        assert params.start_date is not None
        assert params.end_date is not None
        start_utc, end_utc = params.to_utc_datetime_range()
        days = (params.end_date - params.start_date).days + 1
        assert days == 3  # 28, 29, 1

    def test_non_leap_year_february(self) -> None:
        """测试非闰年 2 月"""
        params = TimeRangeParams(
            start_date=date(2025, 2, 28),
            end_date=date(2025, 3, 1),
            tz_offset_minutes=0,
        )
        assert params.start_date is not None
        assert params.end_date is not None
        days = (params.end_date - params.start_date).days + 1
        assert days == 2  # 28, 1

    # ==================== 验证错误测试 ====================

    def test_validate_for_time_series_limit(self) -> None:
        """测试时间序列超过 90 天限制"""
        params = TimeRangeParams(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 4, 5),  # 95 days inclusive
            tz_offset_minutes=0,
        )
        with pytest.raises(ValueError):
            params.validate_for_time_series()

    def test_validate_start_after_end(self) -> None:
        """测试 start_date > end_date 应报错"""
        with pytest.raises(ValueError):
            TimeRangeParams(
                start_date=date(2026, 2, 10),
                end_date=date(2026, 2, 1),
                tz_offset_minutes=0,
            )

    def test_validate_max_days_exceeded(self) -> None:
        """测试超过 365 天限制"""
        with pytest.raises(ValueError):
            TimeRangeParams(
                start_date=date(2025, 1, 1),
                end_date=date(2026, 2, 1),  # > 365 days
                tz_offset_minutes=0,
            )

    def test_validate_hour_granularity_multi_day(self) -> None:
        """测试小时粒度不支持多天"""
        with pytest.raises(ValueError):
            TimeRangeParams(
                start_date=date(2026, 2, 1),
                end_date=date(2026, 2, 2),
                granularity="hour",
                tz_offset_minutes=0,
            )

    def test_validate_missing_dates_and_preset(self) -> None:
        """测试缺少日期和预设应报错"""
        with pytest.raises(ValueError):
            TimeRangeParams(tz_offset_minutes=0)

    # ==================== 完整 UTC 日期分割测试 ====================

    def test_get_complete_utc_dates_aligned(self) -> None:
        """测试 UTC 对齐时无头尾边界"""
        params = TimeRangeParams(
            start_date=date(2026, 2, 1),
            end_date=date(2026, 2, 3),
            tz_offset_minutes=0,  # UTC 对齐
        )
        assert params.start_date is not None
        assert params.end_date is not None
        complete_dates, head, tail = params.get_complete_utc_dates()
        assert len(complete_dates) == 3
        assert head is None
        assert tail is None

    def test_get_complete_utc_dates_with_offset(self) -> None:
        """测试带偏移时产生头尾边界"""
        params = TimeRangeParams(
            start_date=date(2026, 2, 1),
            end_date=date(2026, 2, 3),
            tz_offset_minutes=480,  # UTC+8
        )
        assert params.start_date is not None
        assert params.end_date is not None
        complete_dates, head, tail = params.get_complete_utc_dates()
        # UTC+8 的 2/1 00:00 = UTC 1/31 16:00，会产生头边界
        assert head is not None or tail is not None or len(complete_dates) < 3

    # ==================== 本地日期小时映射测试 ====================

    def test_get_local_day_hours(self) -> None:
        """测试本地日期到 UTC 小时映射"""
        params = TimeRangeParams(
            start_date=date(2026, 2, 1),
            end_date=date(2026, 2, 2),
            tz_offset_minutes=480,  # UTC+8
        )
        assert params.start_date is not None
        assert params.end_date is not None
        local_days = params.get_local_day_hours()
        assert len(local_days) == 2
        for local_date, start_utc, end_utc in local_days:
            assert isinstance(local_date, date)
            assert isinstance(start_utc, datetime)
            assert isinstance(end_utc, datetime)
            # 每天应该正好是 24 小时
            assert (end_utc - start_utc).total_seconds() == 24 * 3600


class TestSplitTimeRangeForHourly:
    """测试小时级时间范围分割"""

    def test_aligned_hours(self) -> None:
        """测试整点对齐的时间范围"""
        start = datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 2, 1, 3, 0, tzinfo=timezone.utc)
        head, complete, tail = split_time_range_for_hourly(start, end)
        assert head is None
        assert tail is None
        assert len(complete) == 3

    def test_with_head_fragment(self) -> None:
        """测试带头部碎片"""
        start = datetime(2026, 2, 1, 0, 30, tzinfo=timezone.utc)
        end = datetime(2026, 2, 1, 3, 0, tzinfo=timezone.utc)
        head, complete, tail = split_time_range_for_hourly(start, end)
        assert head is not None
        assert head[0] == start
        assert head[1] == datetime(2026, 2, 1, 1, 0, tzinfo=timezone.utc)
        assert len(complete) == 2  # 1:00, 2:00

    def test_with_tail_fragment(self) -> None:
        """测试带尾部碎片"""
        start = datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 2, 1, 2, 30, tzinfo=timezone.utc)
        head, complete, tail = split_time_range_for_hourly(start, end)
        assert head is None
        assert tail is not None
        assert tail[0] == datetime(2026, 2, 1, 2, 0, tzinfo=timezone.utc)
        assert tail[1] == end
        assert len(complete) == 2  # 0:00, 1:00

    def test_with_both_fragments(self) -> None:
        """测试同时带头尾碎片"""
        start = datetime(2026, 2, 1, 0, 15, tzinfo=timezone.utc)
        end = datetime(2026, 2, 1, 2, 45, tzinfo=timezone.utc)
        head, complete, tail = split_time_range_for_hourly(start, end)
        assert head is not None
        assert tail is not None
        assert len(complete) == 1  # 只有 1:00-2:00 是完整的
