import asyncio
import logging
from datetime import date
from typing import Dict, Any, Optional
from garminconnect import Garmin

from app.redis.client import get_redis_client

logger = logging.getLogger(__name__)

_SESSION_TTL = 82800  # 23 hours — just under Garmin's 24h token expiry


class AsyncGarminClient:
    """Non-blocking async wrapper around the synchronous garminconnect client.

    Tokens (di_token / di_refresh_token) are cached in Redis so restarts and
    manual polls skip the full login round-trip until the token actually expires.
    """

    def __init__(self, email: str, password: str, user_id: str = ""):
        self.email = email
        self.password = password
        self.user_id = user_id
        self._garmin: Optional[Garmin] = None  # outer Garmin wrapper

    # ------------------------------------------------------------------
    # Session caching
    # ------------------------------------------------------------------

    def _session_key(self) -> str:
        return f"garmin_session:{self.user_id}"

    async def _save_session(self) -> None:
        """Serialises garminconnect tokens to Redis."""
        if not self._garmin or not self.user_id:
            return
        try:
            redis = await get_redis_client()
            token_str = self._garmin.client.dumps()  # JSON: di_token, di_refresh_token, di_client_id
            await redis.set(self._session_key(), token_str, ex=_SESSION_TTL)
            logger.info(f"Garmin session cached in Redis for user {self.user_id}")
        except Exception as e:
            logger.warning(f"Failed to cache Garmin session for user {self.user_id}: {e}")

    async def _try_restore_session(self) -> bool:
        """Loads cached tokens from Redis and validates with a lightweight API call.

        Returns True if the session is still valid; False if absent or expired.
        """
        if not self.user_id:
            return False
        try:
            redis = await get_redis_client()
            raw = await redis.get(self._session_key())
            if not raw:
                return False
            token_str = raw if isinstance(raw, str) else bytes(raw).decode()

            def _restore_and_probe():
                g = Garmin(self.email, self.password)
                # login(tokenstore=...) restores tokens AND fetches the user profile
                # (sets display_name, unit_system, etc.) in one shot.
                # token_str is always >512 chars so the library treats it as raw
                # token data rather than a file path.
                g.login(tokenstore=token_str)
                return g

            self._garmin = await asyncio.to_thread(_restore_and_probe)
            logger.info(f"Garmin session restored from Redis for user {self.user_id}")
            return True
        except Exception as e:
            logger.warning(f"Cached Garmin session invalid for user {self.user_id}: {e}")
            await self.invalidate_session()
            return False

    async def invalidate_session(self) -> None:
        """Clears the in-memory client and the Redis entry."""
        self._garmin = None
        if self.user_id:
            try:
                redis = await get_redis_client()
                await redis.delete(self._session_key())
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------

    async def login(self) -> None:
        """Authenticates against Garmin Connect, trying the Redis cache first."""
        if await self._try_restore_session():
            return

        def _sync_login():
            logger.info(f"Fresh Garmin login for {self.email}…")
            g = Garmin(self.email, self.password)
            g.login()
            return g

        self._garmin = await asyncio.to_thread(_sync_login)
        logger.info(f"Garmin login successful for {self.email}")
        await self._save_session()

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    async def fetch_all_metrics(self) -> Dict[str, Any]:
        """Fetches today's biometric metrics from Garmin Connect."""
        if not self._garmin:
            await self.login()

        today_str = date.today().isoformat()
        garmin = self._garmin  # local ref for the thread

        def _sync_fetch() -> Dict[str, Any]:
            assert garmin is not None
            metrics: Dict[str, Any] = {}

            # 1. Activities — fetch first so we can use as fallback for steps/calories
            activities = []
            try:
                activities = garmin.get_activities_by_date(today_str, today_str) or []
                if activities:
                    latest = activities[-1]
                    metrics["activity"] = {
                        "activity_id": str(latest.get("activityId") or "none"),
                        "type": (latest.get("activityType") or {}).get("typeKey", "unknown"),
                        "duration_minutes": float((latest.get("duration") or 0.0) / 60.0),
                        "calories": float(latest.get("calories") or 0.0),
                        "steps": int(latest.get("steps") or 0),
                    }
            except Exception as e:
                logger.warning(f"Failed to fetch Garmin activity data: {e}")

            # 2. User Summary — steps, stress, body battery
            try:
                summary = garmin.get_user_summary(today_str)
                raw_steps = summary.get("totalSteps")
                raw_stress = summary.get("averageStressLevel")
                raw_bb = summary.get("bodyBatteryMostRecentValue")

                # Steps: prefer wellness summary; fall back to sum of activity steps
                if raw_steps is not None:
                    metrics["steps"] = float(raw_steps)
                else:
                    activity_steps = sum(int(a.get("steps") or 0) for a in activities)
                    if activity_steps > 0:
                        metrics["steps"] = float(activity_steps)
                    # else: omit — no real data

                if raw_stress is not None:
                    metrics["stress"] = float(raw_stress)
                # else: omit — no real data

                if raw_bb is not None:
                    metrics["body_battery"] = float(raw_bb)
                # else: omit — no real data

            except Exception as e:
                logger.warning(f"Failed to fetch Garmin user summary: {e}")
                # Still try activity steps fallback
                if "steps" not in metrics:
                    activity_steps = sum(int(a.get("steps") or 0) for a in activities)
                    if activity_steps > 0:
                        metrics["steps"] = float(activity_steps)

            # 3. Sleep
            try:
                sleep_data = garmin.get_sleep_data(today_str)
                dto = (sleep_data or {}).get("dailySleepDTO", {}) or {}
                duration = dto.get("sleepTimeSeconds")
                score = dto.get("sleepScore")
                if duration is not None or score is not None:
                    metrics["sleep"] = {
                        "duration_seconds": float(duration or 0),
                        "score": float(score or 0),
                    }
                # else: omit — no sleep data recorded
            except Exception as e:
                logger.warning(f"Failed to fetch Garmin sleep data: {e}")

            # 4. HRV
            try:
                hrv_data = garmin.get_hrv_data(today_str)
                hrv_summary = (hrv_data or {}).get("hrvSummary", {}) or {}
                hrv_val = hrv_summary.get("lastNightAvg")
                if hrv_val is not None:
                    metrics["hrv"] = float(hrv_val)
                # else: omit
            except Exception as e:
                logger.warning(f"Failed to fetch Garmin HRV data: {e}")

            # 5. VO2 Max
            try:
                training_data = garmin.get_training_status(today_str) or {}
                generic_vo2 = (training_data.get("mostRecentVO2Max") or {}).get("generic") or {}
                vo2 = generic_vo2.get("vo2MaxPreciseValue") or generic_vo2.get("vo2MaxValue")
                if vo2:  # truthy: skips both None and 0 (sub-1 ml/kg/min is not physiological)
                    metrics["vo2max"] = float(vo2)
                # else: omit
            except Exception as e:
                logger.warning(f"Failed to fetch Garmin VO2max data: {e}")

            # 6. Resting heart rate
            try:
                hr_data = garmin.get_heart_rates(today_str) or {}
                rhr = hr_data.get("restingHeartRate")
                if rhr is not None:
                    metrics["heart_rate"] = float(rhr)
                # else: omit
            except Exception as e:
                logger.warning(f"Failed to fetch Garmin heart rate data: {e}")

            logger.info(f"Garmin fetch complete. Available metrics: {list(metrics.keys())}")
            return metrics

        return await asyncio.to_thread(_sync_fetch)
